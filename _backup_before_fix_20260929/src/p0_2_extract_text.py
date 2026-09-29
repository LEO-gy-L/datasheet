# -*- coding: utf-8 -*-
"""
P0 第 2 步：提取正文（新版）
==========================
输出统一格式：
    [来源] STM32F103C8_Datasheet.pdf
    [页码] 14
    [标题] 第 14 页正文
    [类型] text

    正文内容...

目录页 / 列表页 / 空白页 会被跳过，但原因写入 _report.md。
"""

import argparse
import re
import statistics
from pathlib import Path

try:
    import pymupdf
except ImportError:
    import fitz as pymupdf


# ---------- 配置 ----------
# 页眉/页脚：靠"在页面边缘反复出现"来识别
# 0.12 大约覆盖顶部 100pt / 底部 730pt（STM32 页眉在 y≈78，页脚在 y≈743）
HEADER_FOOTER_MARGIN_RATIO = 0.12
HEADER_FOOTER_MIN_REPEAT = 5   # 同一段文字至少在这么多页边缘出现，才认定为页眉/页脚

TOC_DOT_THRESHOLD = 8          # 一页里出现多少次 "..." 引导点就判定为目录/列表页
TOC_TITLE_KEYWORDS = ("contents", "list of tables", "list of figures")

TABLE_OVERLAP_RATIO = 0.5      # 文本块与表格矩形重叠面积 / 块面积，超过就丢弃
MIN_BLOCK_LEN = 10             # 短于这个长度的块直接丢弃（图内标签/碎片）
GRAPHICS_SHORT_RATIO = 0.65    # 一页里短块占比超过这个值，判定为图形页

CHAR_MAP = {
    "\xa0": " ",
    "\u2013": "-",
    "\u2212": "-",
    "\u2014": "-",
    "\u2022": "-",
    "\u25cf": "-",   # 实心圆点（ATmega 列表符号）
    "\ufb01": "fi",
    "\ufb02": "fl",
}

SENTENCE_PUNCT = re.compile(r"[.:;，。；：!?]")   # 含句子标点的块不是碎片
SECTION_NUM_RE = re.compile(r"^\d+(\.\d+)*\.?$")   # 章节编号，如 6.2 / 14.

# 显式页眉/页脚模式：文档编号、页码、产品型号、官网链接
HEADER_FOOTER_RES = [
    re.compile(r"^DS\d+\s+Rev\s+\d+"),          # DS5319 Rev 20
    re.compile(r"^\d+/\d+"),                    # 1/114, 9/115
    re.compile(r"^STM32F103x[8B],\s+STM32F103x[8B]$"),  # 产品型号页眉
    re.compile(r"^www\.st\.com$"),              # 官网
]


def clean_chars(text: str) -> str:
    """把 PDF 里的特殊 Unicode 字符换成普通字符。"""
    for old, new in CHAR_MAP.items():
        text = text.replace(old, new)
    return text


def looks_like_figure_label(text: str) -> bool:
    """判断一段文字是不是"图里面的标签"（引脚名、刻度、封装尺寸标注）。"""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return True
    if SECTION_NUM_RE.fullmatch(lines[0]):
        return False

    avg_len = sum(len(ln) for ln in lines) / len(lines)

    if len(lines) == 1:
        return avg_len < 25
    return avg_len < 20


def collect_margin_text(doc: pymupdf.Document) -> tuple[dict[str, int], dict[str, int]]:
    """
    分别统计页面顶部和底部边缘反复出现的文字行。

    为什么分顶部/底部：
      - 底部高频 -> 基本是页脚（页码、文档编号）-> 删
      - 顶部底部都高频 -> 真正的页眉页脚 -> 删
      - 只在顶部高频 -> 可能是章节标题（位置不固定，每章不同）-> 保留
    """
    top_counts: dict[str, int] = {}
    bot_counts: dict[str, int] = {}
    h = doc[0].rect.height
    top_y = h * HEADER_FOOTER_MARGIN_RATIO
    bot_y = h * (1 - HEADER_FOOTER_MARGIN_RATIO)

    for page in doc:
        for b in page.get_text("blocks"):
            if b[6] != 0 or not b[4].strip():
                continue
            y0, y1 = b[1], b[3]
            # 顶部边缘
            is_top = y1 < top_y
            # 底部边缘
            is_bot = y0 > bot_y
            if not (is_top or is_bot):
                continue

            target = top_counts if is_top else bot_counts
            for ln in b[4].split("\n"):
                t = clean_chars(ln).strip()
                if len(t) > 2:
                    target[t] = target.get(t, 0) + 1

    return top_counts, bot_counts


def is_toc_or_list_page(page: pymupdf.Page) -> bool:
    """判断一页是不是目录页或表格/图片列表页。"""
    text = page.get_text().lower()
    dots = text.count(".")
    # 目录页/列表页的典型特征：大量 "..." 引导点
    if dots > TOC_DOT_THRESHOLD and "....." in text:
        return True
    # 或者标题里直接出现 Contents / List of tables / List of figures
    first_300 = text[:300]
    for kw in TOC_TITLE_KEYWORDS:
        if kw in first_300:
            return True
    return False


def is_graphics_page(page: pymupdf.Page) -> bool:
    """判断一页是不是以图/框图为主（引脚图、封装图、时序图）。"""
    blocks = [b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
    if not blocks:
        return False

    short_count = 0
    for b in blocks:
        t = clean_chars(b[4]).strip()
        # 短块 或 单行无标点块 都可能是图内标签
        if len(t) < 18 or (len(t) < 30 and not SENTENCE_PUNCT.search(t)):
            short_count += 1

    return short_count / len(blocks) > GRAPHICS_SHORT_RATIO


def extract_page(page: pymupdf.Page, doc_title: str,
                 table_rects: list[tuple[float, float, float, float]],
                 hf_candidates: set[str]) -> tuple[str, dict]:
    """处理一页，返回 (清洗后的正文, 统计信息)。"""
    stats = {
        "total": 0, "header_footer": 0, "table": 0,
        "fragment": 0, "graphics_label": 0, "kept": 0,
    }

    if is_toc_or_list_page(page):
        return "", {**stats, "skipped": "目录/列表页"}

    is_graphics = is_graphics_page(page)

    blocks = [b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
    stats["total"] = len(blocks)

    kept_texts: list[str] = []
    for b in blocks:
        x0, y0, x1, y1, raw = b[0], b[1], b[2], b[3], b[4]
        text = clean_chars(raw).strip()

        # R1：页眉/页脚。逐行检查，删除：
        #   1. 在底部高频出现的行（页脚）
        #   2. 同时出现在顶部和底部的高频行（页眉页脚）
        #   3. 显式匹配页眉/页脚正则的行（产品型号、文档编号、页码、官网）
        lines = [ln.strip() for ln in text.split("\n")]
        filtered_lines = []
        removed_hf = False
        for ln in lines:
            if ln in hf_candidates:
                stats["header_footer"] += 1
                removed_hf = True
                continue
            if any(hf_re.fullmatch(ln) for hf_re in HEADER_FOOTER_RES):
                stats["header_footer"] += 1
                removed_hf = True
                continue
            filtered_lines.append(ln)

        if not filtered_lines or all(not ln for ln in filtered_lines):
            continue

        text = "\n".join(filtered_lines)

        # 如果一个块只去掉页眉页脚后变成空或只剩很短内容，跳过
        if removed_hf and len(text) < MIN_BLOCK_LEN and not SENTENCE_PUNCT.search(text):
            stats["fragment"] += 1
            continue

        # R2：落在表格区域内的文字（避免与表格产物重复）
        block_area = (x1 - x0) * (y1 - y0)
        if block_area > 0 and any(
            rect_overlap((x0, y0, x1, y1), tr) / block_area > TABLE_OVERLAP_RATIO
            for tr in table_rects
        ):
            stats["table"] += 1
            continue

        # R3：过短的碎片
        if len(text) < MIN_BLOCK_LEN and not SENTENCE_PUNCT.search(text):
            stats["fragment"] += 1
            continue

        # R4：图形页上的图内标签
        if is_graphics and looks_like_figure_label(text):
            stats["graphics_label"] += 1
            continue

        # 保留
        if text:
            kept_texts.append(text)
            stats["kept"] += 1

    if not kept_texts:
        reason = "图形页" if is_graphics else "空白页"
        return "", {**stats, "skipped": reason}

    return "\n\n".join(kept_texts), stats


def rect_overlap(a: tuple[float, float, float, float],
                 b: tuple[float, float, float, float]) -> float:
    """计算两个矩形重叠面积。"""
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    if x0 >= x1 or y0 >= y1:
        return 0.0
    return (x1 - x0) * (y1 - y0)


def write_page(out_dir: Path, page_no: int, pdf_name: str, title: str,
               content: str, doc_type: str = "text") -> None:
    """按统一格式写出单页 Markdown。"""
    md = (
        f"[来源] {pdf_name}\n"
        f"[页码] {page_no}\n"
        f"[标题] {title}\n"
        f"[类型] {doc_type}\n\n"
        f"{content}\n"
    )
    (out_dir / f"page_{page_no:03d}.md").write_text(md, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="从 PDF 提取正文")
    parser.add_argument("--pdf", default="datasheets/STM32F103C8_Datasheet.pdf",
                        help="输入 PDF 路径")
    parser.add_argument("--out-dir", default=None,
                        help="输出目录，默认 data/text_v2/<pdf_stem>/")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    pdf_name = pdf_path.name
    stem = pdf_path.stem

    out_dir = Path(args.out_dir) if args.out_dir else Path("data/text_v2") / stem
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(pdf_path)

    # 先全局统计页眉/页脚候选
    top_counts, bot_counts = collect_margin_text(doc)
    # 底部高频 = 页脚；顶部底部都高频 = 页眉/页脚
    hf_candidates = set()
    for t, c in bot_counts.items():
        if c >= HEADER_FOOTER_MIN_REPEAT:
            hf_candidates.add(t)
    for t, c in top_counts.items():
        if c >= HEADER_FOOTER_MIN_REPEAT and t in bot_counts:
            hf_candidates.add(t)

    # 表格矩形，避免正文与表格重复
    table_rects: list[tuple[float, float, float, float]] = []
    for page in doc:
        for t in page.find_tables().tables:
            table_rects.append(t.bbox)

    grand = {"total": 0, "header_footer": 0, "table": 0,
             "fragment": 0, "graphics_label": 0, "kept": 0}
    written = 0
    skipped: list[tuple[int, str]] = []

    for pno in range(len(doc)):
        page = doc[pno]
        text, stats = extract_page(page, stem, table_rects, hf_candidates)

        for k in grand:
            grand[k] += stats.get(k, 0)

        if not text:
            skipped.append((pno + 1, stats.get("skipped", "无内容")))
            continue

        write_page(out_dir, pno + 1, pdf_name, f"第 {pno + 1} 页正文", text, "text")
        written += 1

    # 写报告
    report_lines = [
        f"# 正文提取报告：{pdf_name}",
        f"",
        f"- 总页数：{len(doc)}",
        f"- 输出页数：{written}",
        f"- 跳过页数：{len(skipped)}",
        f"- 保留正文块：{grand['kept']}",
        f"- 剔除页眉/页脚：{grand['header_footer']}",
        f"- 剔除表格区文字：{grand['table']}",
        f"- 剔除碎片：{grand['fragment']}",
        f"- 剔除图内标签：{grand['graphics_label']}",
        f"",
        f"## 跳过的页",
        f"",
    ]
    for page_no, reason in skipped:
        report_lines.append(f"- 第 {page_no} 页：{reason}")

    report_lines.extend([
        f"",
        f"## 高频页眉/页脚（底部 ≥{HEADER_FOOTER_MIN_REPEAT} 次）",
        f"",
    ])
    for t, c in sorted(bot_counts.items(), key=lambda x: -x[1]):
        if c >= HEADER_FOOTER_MIN_REPEAT:
            report_lines.append(f"- 底部出现 {c} 次：{t!r}")

    (out_dir / "_report.md").write_text("\n".join(report_lines), encoding="utf-8")

    print(f"正文提取完成：{pdf_name}")
    print(f"  输出页数：{written}")
    print(f"  跳过页数：{len(skipped)}")
    print(f"  输出目录：{out_dir}")
    print(f"  报告：{out_dir / '_report.md'}")


if __name__ == "__main__":
    main()
