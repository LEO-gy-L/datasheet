# -*- coding: utf-8 -*-
"""
P0 第 2 步：提取正文（新线路的唯一正文脚本）
===========================================

输出统一格式：
    [来源] STM32F103C8_Datasheet.pdf
    [页码] 14
    [标题] 第 14 页正文
    [类型] text

    正文内容...

目录页 / 列表页 / 空白页 会被跳过，但原因写入 _report.md。

────────────────────────────────────────────────────────────────
2026-09-29 修复记录（这次改了三处，都写清楚原因，方便以后回看）
────────────────────────────────────────────────────────────────
【修复 1】表格矩形跨页污染 —— 这是最严重的一个 bug
    旧写法在 main() 里把所有页的表格矩形累进一个全局列表 table_rects，
    然后 extract_page() 对每一页都拿这个全局列表去判断重叠。
    但 PDF 每一页的坐标系尺寸是一样的，所以第 37 页那张表
    （y 大约在 300~500）会命中第 10 页 y 也在 300~500 的正文块，
    把这些正常正文当成"表格区文字"删掉 —— 而且一声不吭。
    实测：全文档有 2179 个正文块是这样被误杀的，
          text_v2 的正文比正确的 text_v1 少了约 84%。
    改法：把取表格矩形这件事挪进 extract_page()，只取"本页"的表格。
          （旧的 p0_3_text.py 本来就是这么写的，所以它输出是对的；
            本脚本现在和它保持一致。）

【修复 2】路径不锚定项目根
    旧写法用 Path("data/text_v2")，能不能跑取决于你当前在哪个目录敲命令。
    现在统一用 ROOT（= 项目根）拼绝对路径。

【修复 3】补上"段落合并"merge_lines()
    旧写法直接丢掉，导致 PDF 里被排版成 3 行的同一句话，输出里就是 3 行。
    切块时按空行切，一句话就可能被拆散，检索匹配不上。
"""

import argparse
import re
from pathlib import Path

try:
    import pymupdf
except ImportError:
    import fitz as pymupdf


# ---------- 项目根目录 ----------
# 项目根目录：统一定义在 backend/app/config.py
# 用绝对路径的好处：不管你在 C:\ 还是项目根敲命令，读写的位置都对。
from backend.app.config import ROOT


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

# 段落合并用：以这些开头的行，视为"新的一段"，不接到上一行后面
NEW_ITEM_RE = re.compile(r"^(-|\*|\d+\.|\d+\))\s")


def clean_chars(text: str) -> str:
    """把 PDF 里的特殊 Unicode 字符换成普通字符。"""
    for old, new in CHAR_MAP.items():
        text = text.replace(old, new)
    # 连续 2 个以上空格压成 1 个（PDF 排版常有连续空格）
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text


def merge_lines(text: str) -> str:
    """
    把 PDF 提取出来的"多行"接成正常的段落。

    为什么需要（这是修复 3 的重点）：
        PDF 是按"视觉行"存字的。一句话在纸面上排成 3 行，
        page.get_text("blocks") 出来就是 3 行文本。
        下游切块是按空行切的，不合并的话一句话可能被拆到两个块里。

    规则：默认把下一行接到上一行后面（用空格连接）；
         遇到以 "-" "•" "1." 开头的行，认为是新的一段，保留换行。
         上一行以连字符结尾时，说明单词被折断了（"charact-" + "eristic"），
         直接拼起来、不留空格。
    """
    lines = [ln.strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]
    if not lines:
        return ""

    out: list[str] = [lines[0]]
    for ln in lines[1:]:
        if NEW_ITEM_RE.match(ln):
            out.append("\n" + ln)               # 新的列表项，保留换行
        else:
            prev = out[-1]
            if prev.endswith("-") and not prev.endswith(" -"):
                out[-1] = prev[:-1] + ln        # 单词被折断，拼回去
            else:
                out[-1] = prev + " " + ln
    return "".join(out)


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
            is_top = y1 < top_y     # 顶部边缘
            is_bot = y0 > bot_y     # 底部边缘
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
    # 目录页的典型特征：大量 "..." 引导点。
    # 注意排版有两种写法，都要认：
    #   "Table 6 .......... 37"     连续点（STM32 部分页）
    #   "Table 6 . . . . . . 37"    间隔点（ATmega 用得多，能骗过 "....." 判断）
    # 只认连续点的话，间隔点那种目录页会漏网，
    # 于是 "5.3.3 Embedded reset ... . . . 39" 这种行会被当成正文的小节标题。
    spaced_dots = bool(re.search(r"\.\s\.\s\.\s\.\s\.", text))
    if dots > TOC_DOT_THRESHOLD and ("....." in text or spaced_dots):
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


def extract_page(page: pymupdf.Page,
                 hf_candidates: set[str]) -> tuple[str, dict]:
    """
    处理一页，返回 (清洗后的正文, 统计信息)。

    ── 这里就是【修复 1】的关键位置 ──
    表格矩形在函数体内部取，只取"本页"的：
        table_rects = [t.bbox for t in page.find_tables().tables]
    绝对不能由外部传进来一个"全文档汇总"的列表，
    否则别的页的表格坐标会误伤本页正文（详见文件顶部的修复 1 说明）。
    """
    stats = {
        "total": 0, "header_footer": 0, "table": 0,
        "fragment": 0, "graphics_label": 0, "kept": 0,
    }

    if is_toc_or_list_page(page):
        return "", {**stats, "skipped": "目录/列表页"}

    # 【修复 1】只取本页的表格矩形
    table_rects = [t.bbox for t in page.find_tables().tables]

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
        #     这里比的是"本页表格"，不会再跨页误伤
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

        # 保留（【修复 3】先做段落合并，再收进正文）
        merged = merge_lines(text)
        if merged:
            kept_texts.append(merged)
            stats["kept"] += 1

    if not kept_texts:
        reason = "图形页" if is_graphics else "空白页"
        return "", {**stats, "skipped": reason}

    return "\n\n".join(kept_texts), stats


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
                        help="输入 PDF 路径（相对项目根目录）")
    parser.add_argument("--out-dir", default=None,
                        help="输出目录，默认 data/text_v2/<pdf_stem>/")
    args = parser.parse_args()

    # 【修复 2】路径统一锚定到项目根：相对路径按"项目根"解释
    pdf_path = Path(args.pdf)
    if not pdf_path.is_absolute():
        pdf_path = ROOT / pdf_path
    pdf_name = pdf_path.name
    stem = pdf_path.stem

    if not pdf_path.exists():
        print(f"[错误] 找不到 PDF：{pdf_path}")
        print("       --pdf 是相对项目根目录的路径，例如 datasheets/STM32F103C8_Datasheet.pdf")
        return

    if args.out_dir:
        out_dir = Path(args.out_dir)
        if not out_dir.is_absolute():
            out_dir = ROOT / out_dir
    else:
        out_dir = ROOT / "data" / "text_v2" / stem
    out_dir.mkdir(parents=True, exist_ok=True)

    # 清掉上一次运行残留的页文件（否则本次跳过的页面会留下旧内容）
    # 安全护栏：只删 "page_数字.md"，且路径里必须有一段以 text_v 开头，
    # 防止 --out-dir 传错目录误删别的东西
    stale = sorted(out_dir.glob("page_*.md"))
    if stale:
        if any(p.startswith("text_v") for p in out_dir.parts):
            for f in stale:
                f.unlink()
            print(f"已清理旧输出 {len(stale)} 个 page_*.md")
        else:
            print(f"[警告] 输出路径里没有 text_v 开头的目录段（{out_dir}），"
                  f"为安全起见不自动清理旧文件，已跳过")

    doc = pymupdf.open(pdf_path)

    # 先全局统计页眉/页脚候选
    top_counts, bot_counts = collect_margin_text(doc)
    # 底部高频 = 页脚；顶部底部都高频 = 页眉/页脚
    hf_candidates: set[str] = set()
    for t, c in bot_counts.items():
        if c >= HEADER_FOOTER_MIN_REPEAT:
            hf_candidates.add(t)
    for t, c in top_counts.items():
        if c >= HEADER_FOOTER_MIN_REPEAT and t in bot_counts:
            hf_candidates.add(t)

    grand = {"total": 0, "header_footer": 0, "table": 0,
             "fragment": 0, "graphics_label": 0, "kept": 0}
    written = 0
    skipped: list[tuple[int, str]] = []

    for pno in range(len(doc)):
        page = doc[pno]
        text, stats = extract_page(page, hf_candidates)

        for k in grand:
            grand[k] += stats.get(k, 0)

        if not text:
            skipped.append((pno + 1, stats.get("skipped", "无内容")))
            continue

        write_page(out_dir, pno + 1, pdf_name, f"第 {pno + 1} 页正文", text, "text")
        written += 1

    doc.close()

    # 写报告
    report_lines = [
        f"# 正文提取报告：{pdf_name}",
        f"",
        f"- 总页数：{len(skipped) + written}",
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

    total_chars = sum(
        len(f.read_text(encoding="utf-8"))
        for f in out_dir.glob("page_*.md")
    )

    print(f"正文提取完成：{pdf_name}")
    print(f"  输出页数：{written}")
    print(f"  跳过页数：{len(skipped)}")
    print(f"  保留正文块：{grand['kept']}")
    print(f"  剔除表格区文字：{grand['table']}")
    print(f"  正文总字符数：{total_chars:,}")
    print(f"  输出目录：{out_dir}")
    print(f"  报告：{out_dir / '_report.md'}")


if __name__ == "__main__":
    main()
