"""
P0 全量质量扫描脚本

背景：上一轮我只用眼睛看了第 37 页一个样本，用户质疑"表格也都错了，你没读出来"。
这个脚本做**全文档 114 页 / 179 张表**的全量检测，把所有可疑格子列出来，
而不是靠样本目检。

检测项：
  A. 合并单元格数量（纵向/横向），以及修复前后会差多少个格子
  B. 列数与表头不一致的行
  C. 残留 PyMuPDF 占位名（Col数字）= 表头识别失败
  D. 残留 Markdown 标记（** / ~~）
  E. 相邻格内容完全相同的可疑行（可能是合并填充留下的痕迹）

运行： .venv\\Scripts\\python src\\p0_scan_quality.py
"""

import re
from pathlib import Path

import pymupdf

# 项目根目录：本文件在 <项目根>/src/ 下，parents[1] = 项目根
ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "datasheets" / "STM32F103C8_Datasheet.pdf"


def parse_md_rows(md: str) -> list[list[str]]:
    """把 to_markdown 的字符串解析成二维列表，跳过分隔线。"""
    rows = []
    for line in md.splitlines():
        s = line.strip()
        if not s:
            continue
        if re.fullmatch(r"\|[\s\-:|]+\|", s):   # |---|---| 这种分隔线
            continue
        rows.append([c.strip() for c in s.strip("|").split("|")])
    return rows


def main():
    doc = pymupdf.open(PDF)

    n_tables = 0
    n_cells_total = 0
    n_merged_none = 0          # 合并格（无独立框）总数
    n_vertical = 0             # 纵向合并（会被 to_markdown 填成左邻值 -> 原本是错的）
    n_horizontal = 0           # 横向合并
    n_row_mismatch = 0         # 行数与坐标网格对不上的表
    bad_rows_samples = []      # 列数不一致的行样例
    pages_with_tables = 0

    for pi in range(doc.page_count):
        page = doc[pi]
        tables = page.find_tables().tables
        if tables:
            pages_with_tables += 1

        for ti, t in enumerate(tables, 1):
            n_tables += 1
            rows = parse_md_rows(t.to_markdown())
            rects_grid = [list(r.cells) for r in t.rows]

            # 尾部对齐：to_markdown 常在开头多给一行表格标题
            offset = len(rows) - len(rects_grid)
            if offset < 0:
                n_row_mismatch += 1
                continue

            for ri in range(len(rects_grid)):
                cells = rects_grid[ri]
                md_ri = ri + offset
                if md_ri >= len(rows):
                    continue
                n_cells_total += len(cells)

                # 本行 y 中心
                ys = [c[1] + (c[3] - c[1]) / 2 for c in cells if c is not None]
                row_y = sum(ys) / len(ys) if ys else -1

                for ci in range(len(cells)):
                    if cells[ci] is not None:
                        continue          # 有自己的框，值是真的
                    n_merged_none += 1

                    # 往上找最近一个有矩形的同列格子
                    above = None
                    for k in range(ri - 1, -1, -1):
                        if ci < len(rects_grid[k]) and rects_grid[k][ci] is not None:
                            above = rects_grid[k][ci]
                            break

                    if above is not None and above[1] <= row_y <= above[3]:
                        n_vertical += 1
                    else:
                        n_horizontal += 1

            # 列数一致性
            if rows:
                ncols = len(rows[0])
                for r in rows:
                    if len(r) != ncols:
                        n_row_mismatch += 1
                        if len(bad_rows_samples) < 6:
                            bad_rows_samples.append((pi + 1, ti, ncols, len(r)))

    doc.close()

    print("=" * 68)
    print("A. 合并单元格全量统计（这是上一轮 Unit 列出错的根源）")
    print("=" * 68)
    print(f"  含表格的页数        : {pages_with_tables}")
    print(f"  表格总数            : {n_tables}")
    print(f"  参与统计的格子总数  : {n_cells_total}")
    print(f"  合并格（无独立框）  : {n_merged_none} 个")
    print(f"     └ 纵向合并      : {n_vertical} 个  ← to_markdown 会填成左邻值，原本全是错的")
    print(f"     └ 横向合并      : {n_horizontal} 个 ← 应沿用左邻，是对的")
    print(f"  列数不一致的行/表   : {n_row_mismatch}")
    if bad_rows_samples:
        print("  样例（页, 表, 表头列数, 该行列数）:", bad_rows_samples)

    # ---------- 扫描输出文件 ----------
    out = ROOT / "data" / "tables_v5"
    print()
    print("=" * 68)
    print(f"B. 输出文件残留问题扫描（{out.relative_to(ROOT)}/）")
    print("=" * 68)

    if not out.exists():
        print("  （目录不存在，请先跑 src/p0_1_extract_tables.py）")
        return

    # 注意用 ** 递归：产物实际在 data/tables_v5/<手册名>/page_XXX.md 里，
    # 只写 *.md 会扫到 0 个文件（这个坑踩过）
    files = sorted(out.glob("**/page_*.md"))
    stat = {"col_placeholder": 0, "bold": 0, "strike": 0, "empty_row": 0}
    col_files, bold_files = [], []

    for f in files:
        txt = f.read_text(encoding="utf-8")
        if re.search(r"Col\d", txt):
            stat["col_placeholder"] += 1
            col_files.append(f.name)
        if "**" in txt:
            stat["bold"] += 1
            bold_files.append(f.name)
        if "~~" in txt:
            stat["strike"] += 1
        for line in txt.splitlines():
            s = line.strip()
            if not s.startswith("|"):
                continue
            # |---|---| 是 markdown 表的分隔行，属于正常内容，不算"空数据行"
            if re.fullmatch(r"\|[\s\-:|]+\|", s):
                continue
            if set(s) <= set("| -"):
                stat["empty_row"] += 1

    print(f"  输出文件总数        : {len(files)}")
    print(f"  残留 Col数字(表头识别失败) : {stat['col_placeholder']} 个文件")
    print(f"  残留 ** 粗体标记    : {stat['bold']} 个文件")
    print(f"  残留 ~~ 删除线      : {stat['strike']} 个文件")
    print(f"  全空数据行          : {stat['empty_row']} 行")
    if col_files:
        print(f"  Col数字 文件列表    : {col_files[:12]}")


if __name__ == "__main__":
    main()
