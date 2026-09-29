# -*- coding: utf-8 -*-
"""
P0 第 1 步：提取并过滤表格（新版）
==================================
把 PDF 里的表格解析成 Markdown，过滤掉图内标注伪表，
输出统一格式：
    [来源] STM32F103C8_Datasheet.pdf
    [页码] 37
    [标题] Table 6. Voltage characteristics
    [类型] table

    | Symbol | Ratings | ...
"""

import argparse
import re
from pathlib import Path

try:
    import pymupdf
except ImportError:
    import fitz as pymupdf


# ---------- 配置 ----------
TITLE_SEARCH_PT = 60.0       # 在表格上边框上方 60pt 内搜索标题

# 伪表过滤阈值
DRAW_RATIO_MAX = 0.35          # 图形重叠率超过这个值 -> 伪表
PLACEHOLDER_RE = re.compile(r"^Col\d+|^Column\d+|^列\d+")
MIN_TRUE_ROWS = 2              # 真表至少要有 2 行数据
MIN_TRUE_COLS = 2              # 真表至少要有 2 列
MIN_TRUE_CELLS = 4             # 真表至少要有 4 个格子

CHAR_MAP = {
    "\xa0": " ",
    "\u2013": "-",
    "\u2212": "-",
    "\u2014": "-",
    "\u2022": "-",
    "\ufb01": "fi",
    "\ufb02": "fl",
}


def clean_chars(text: str) -> str:
    for old, new in CHAR_MAP.items():
        text = text.replace(old, new)
    return text


def parse_markdown_table(md: str) -> tuple[list[str], list[list[str]]]:
    """把 markdown 表格拆成 header 行 + 数据行。"""
    lines = [ln for ln in md.splitlines() if ln.strip() and not re.fullmatch(r"\|[\s\-:|]+\|", ln.strip())]
    if not lines:
        return [], []
    header = [c.strip() for c in lines[0].split("|")[1:-1]]
    rows = [[c.strip() for c in ln.split("|")[1:-1]] for ln in lines[1:]]
    return header, rows


def build_markdown_table(header: list[str], rows: list[list[str]]) -> str:
    """重新拼装 markdown 表格。"""
    def fmt(cells: list[str]) -> str:
        return "| " + " | ".join(cells) + " |"

    sep = "|" + "|".join([" --- " for _ in header]) + "|"
    lines = [fmt(header), sep]
    for r in rows:
        # 确保列数一致
        r = r + [""] * (len(header) - len(r)) if len(r) < len(header) else r[:len(header)]
        lines.append(fmt(r))
    return "\n".join(lines)


def align_columns(header: list[str], rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    """
    对单列多行的表头（多级表头）做列对齐。
    返回的是 (header, rows)，其中 header 只保留最底行作为列名。
    """
    if not rows:
        return header, rows

    n_cols = max(len(r) for r in [header] + rows)
    if n_cols == len(header):
        return header, rows

    # 如果 header 行数比列数少，说明是多级表头被压扁了，
    # 这里用最简单的策略：把 header 和第一行数据合并看列数
    # 更复杂的跨行合并需要坐标信息，这里降级为"保留能解析的部分"
    new_header = [header[i] if i < len(header) else f"Col{i + 1}" for i in range(n_cols)]
    return new_header, rows


def fill_merged_cells(table, header: list[str], rows: list[list[str]]) -> list[list[str]]:
    """
    用坐标判断哪些格子是合并单元格，并做前向填充。
    """
    grid = [list(r.cells) for r in table.rows]
    if not grid or not rows:
        return rows

    filled: list[list[str]] = []
    for ri, row_cells in enumerate(grid):
        if ri >= len(rows):
            break
        new_row = list(rows[ri])
        # 确保列数补齐
        while len(new_row) < len(row_cells):
            new_row.append("")

        for ci, cell_rect in enumerate(row_cells):
            if cell_rect is not None:
                continue

            # 判断合并方向：纵向 or 横向
            # 纵向合并：上方同列的 cell 纵向覆盖本行
            merged = False
            for rj in range(ri - 1, -1, -1):
                above = grid[rj][ci]
                if above is None:
                    continue
                above_y0, above_y1 = above[1], above[3]
                this_y0, this_y1 = table.rows[ri].bbox[1], table.rows[ri].bbox[3]
                # 如果上方格子的 y 范围覆盖本行，说明是纵向合并
                if above_y0 <= this_y0 and above_y1 >= this_y1:
                    if ci < len(filled[rj]):
                        new_row[ci] = filled[rj][ci]
                    merged = True
                    break

            # 横向合并：取左邻值
            if not merged and ci > 0:
                new_row[ci] = new_row[ci - 1]

        filled.append(new_row)

    return filled


def find_table_title(page: pymupdf.Page, table) -> str | None:
    """在表格上方搜索 'Table N.' 形式的标题。"""
    x0, y0, x1, y1 = table.bbox
    search_rect = pymupdf.Rect(x0 - 20, max(0, y0 - TITLE_SEARCH_PT), x1 + 20, y0)

    # 用 words 模式精确获取搜索区域内的文字
    words = page.get_text("words", clip=search_rect)
    if not words:
        return None

    # 按行分组
    lines: dict[int, list[tuple[str, float]]] = {}
    for w in words:
        text, y = w[4], w[3]
        line_y = round(y, 1)
        lines.setdefault(line_y, []).append((text, y))

    # 找离表格最近的一行，匹配 Table N.
    title_re = re.compile(r"Table\s*\d+[.:]\s*.+", re.I)
    candidates = []
    for y, words_list in sorted(lines.items()):
        line_text = " ".join(w[0] for w in sorted(words_list, key=lambda x: x[1]))
        if title_re.search(line_text):
            candidates.append((y, line_text))

    if candidates:
        return clean_chars(candidates[-1][1]).strip()

    return None


def table_to_markdown_v2(page: pymupdf.Page, table) -> tuple[str | None, str]:
    """
    把 pymupdf 表格对象转成干净的 Markdown。
    返回 (标题, markdown)。
    """
    md = table.to_markdown()
    if not md:
        return None, ""

    header, rows = parse_markdown_table(md)
    if not header:
        return None, ""

    # 对齐列数
    header, rows = align_columns(header, rows)

    # 修复合并单元格
    rows = fill_merged_cells(table, header, rows)

    # 清洗每个单元格
    header = [clean_chars(h).strip() for h in header]
    rows = [[clean_chars(c).strip() for c in r] for r in rows]

    title = find_table_title(page, table)
    md = build_markdown_table(header, rows)
    return title, md


def rect_overlap_ratio(table_bbox: tuple[float, float, float, float],
                       drawings: list[dict]) -> float:
    """计算表格与页面图形的重叠面积比例。"""
    x0, y0, x1, y1 = table_bbox
    area = max((x1 - x0) * (y1 - y0), 1e-9)
    overlap = 0.0
    for d in drawings:
        if d.get("fill") is not None:
            continue
        r = d.get("rect")
        if r is None:
            continue
        ox = max(0.0, min(x1, r.x1) - max(x0, r.x0))
        oy = max(0.0, min(y1, r.y1) - max(y0, r.y0))
        if ox > 0 and oy > 0:
            overlap += min(ox * oy, area)
    return min(overlap / area, 1.0)


def calc_features(table, md: str, draw_ratio: float) -> dict:
    """计算一张表的伪表特征。"""
    header, rows = parse_markdown_table(md)
    if not header:
        return {"n_rows": 0, "n_cols": 0, "placeholder_ratio": 0.0, "draw_ratio": draw_ratio}

    all_cells = [c for r in rows for c in r]
    nonempty = [c for c in all_cells if c]
    placeholder_ratio = (
        sum(1 for c in header if PLACEHOLDER_RE.match(c)) / len(header)
        if header else 0.0
    )

    avg_len = sum(len(c) for c in nonempty) / len(nonempty) if nonempty else 0.0
    return {
        "n_rows": len(rows),
        "n_cols": len(header),
        "placeholder_ratio": placeholder_ratio,
        "avg_cell_len": avg_len,
        "draw_ratio": draw_ratio,
    }


def judge(title: str | None, f: dict) -> tuple[bool, str]:
    """判断一张表是否是真表。返回 (保留?, 原因)。"""
    # 有明确 Table N 标题 -> 大概率真表，但图形重叠太高仍要排除
    if title:
        if f["draw_ratio"] > DRAW_RATIO_MAX:
            return False, f"图形重叠率 {f['draw_ratio']:.0%} 过高（封装图/框图标签）"
        return True, f"有标题：{title}"

    # 无标题 -> 严格审查
    if f["n_rows"] < MIN_TRUE_ROWS or f["n_cols"] < MIN_TRUE_COLS:
        return False, f"规模过小（{f['n_rows']} 行 {f['n_cols']} 列）"

    total_cells = f["n_rows"] * f["n_cols"]
    if total_cells < MIN_TRUE_CELLS:
        return False, f"格子数太少（{total_cells}）"

    if f["placeholder_ratio"] > 0.5:
        return False, f"占位列比例 {f['placeholder_ratio']:.0%}"

    if f["draw_ratio"] > DRAW_RATIO_MAX:
        return False, f"图形重叠率 {f['draw_ratio']:.0%} 过高"

    if f["avg_cell_len"] < 3.0:
        return False, f"内容过碎（平均 {f['avg_cell_len']:.1f} 字符）"

    return True, "无标题但结构完整，保留待复核"


def write_table(out_dir: Path, page_no: int, table_idx: int, pdf_name: str,
                title: str, md: str) -> None:
    """按统一格式输出单张表格。"""
    content = (
        f"[来源] {pdf_name}\n"
        f"[页码] {page_no}\n"
        f"[标题] {title}\n"
        f"[类型] table\n\n"
        f"{md}\n"
    )
    # 一页多表时追加到同一个文件
    page_file = out_dir / f"page_{page_no:03d}.md"
    if page_file.exists():
        page_file.write_text(page_file.read_text(encoding="utf-8") + "\n" + content, encoding="utf-8")
    else:
        page_file.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="从 PDF 提取并过滤表格")
    parser.add_argument("--pdf", default="datasheets/STM32F103C8_Datasheet.pdf",
                        help="输入 PDF 路径")
    parser.add_argument("--out-dir", default=None,
                        help="输出目录，默认 data/tables_v5/<pdf_stem>/")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    pdf_name = pdf_path.name
    stem = pdf_path.stem

    out_dir = Path(args.out_dir) if args.out_dir else Path("data/tables_v5") / stem
    out_dir.mkdir(parents=True, exist_ok=True)

    # 清理旧输出
    for f in out_dir.glob("page_*.md"):
        f.unlink()

    doc = pymupdf.open(pdf_path)

    kept = 0
    dropped = 0
    dropped_log: list[tuple[int, int, str]] = []   # (page, table_idx, reason)

    for pno in range(len(doc)):
        page = doc[pno]
        drawings = page.get_drawings()

        tables = page.find_tables().tables
        for ti, table in enumerate(tables, start=1):
            title, md = table_to_markdown_v2(page, table)
            draw_ratio = rect_overlap_ratio(table.bbox, drawings)
            f = calc_features(table, md, draw_ratio)
            keep, reason = judge(title, f)

            if not keep:
                dropped += 1
                dropped_log.append((pno + 1, ti, reason))
                continue

            display_title = title or f"第 {pno + 1} 页 表 {ti}"
            write_table(out_dir, pno + 1, ti, pdf_name, display_title, md)
            kept += 1

    # 写过滤报告
    report = [
        f"# 表格提取报告：{pdf_name}",
        f"",
        f"- 候选表格数：{kept + dropped}",
        f"- 保留表格数：{kept}",
        f"- 剔除表格数：{dropped}",
        f"",
        f"## 剔除明细",
        f"",
    ]
    for page_no, ti, reason in dropped_log:
        report.append(f"- 第 {page_no} 页 表 {ti}：{reason}")

    (out_dir / "_filtered_out.md").write_text("\n".join(report), encoding="utf-8")

    print(f"表格提取完成：{pdf_name}")
    print(f"  保留：{kept} 张")
    print(f"  剔除：{dropped} 张")
    print(f"  输出目录：{out_dir}")


if __name__ == "__main__":
    main()
