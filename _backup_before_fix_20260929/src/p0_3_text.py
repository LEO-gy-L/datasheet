# -*- coding: utf-8 -*-
"""
P0 第 3 步：从 PDF 提取「正文文本」并清洗
================================================================
为什么要有这一步：
  P0 第 2 步只提取了「表格」（80 张），但数据手册里还有大量正文——
  比如"这个芯片有几个定时器""ADC 分辨率是多少"这类答案在正文里，
  不在表格里。所以表格和正文要分别提取，最后一起入库。

本脚本做什么：
  逐页读取文本块 -> 按 5 条规则剔除垃圾 -> 清洗字符 -> 输出成 Markdown

5 条剔除规则（全部基于实测数据得出）：
  R1 页眉   ：块的底边 y < 72pt（实测页眉永远在 y=59 附近）
  R2 页脚   ：块在页面下部且内容是 "DS5319 Rev 20" / "37/115" 这种页码格式
  R3 表格区 ：块有 50% 以上面积落在某张表格的矩形框内（表格已单独提取，避免重复）
  R4 目录页 ：整页都是 ". . . . ." 引导点的，是目录/图表索引，整页丢弃
  R5 碎片   ：长度 < 12 字且不含句子标点的块，是图里的引脚名、图纸编号

消耗 token 吗：
  不消耗。只用 pymupdf（本地解析）+ re（正则）+ pathlib（写文件），
  全程离线，跟大模型没有任何关系。

运行方法：
    .venv\\Scripts\\python src\\p0_3_text.py
    .venv\\Scripts\\python src\\p0_3_text.py --pdf datasheets/ATmega328P_Datasheet.pdf
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import pymupdf

# ==================================================================
# 参数区（所有可调阈值都集中在这里，改这一块就行）
# ==================================================================

# ---------------------------------------------------------------
# R1/R2「页眉页脚」判据的改版说明
# ---------------------------------------------------------------
# 最初版本是按【页面位置】剔除的：块底边 y < 72 就当页眉、在页面下部
# 且长得像 "DS5319 Rev 20" 就当页脚。这个规则在 STM32 手册上完美工作，
# 但一换到 ATmega328P 手册立刻失效 —— 实测发现：
#     STM32  页眉 "STM32F103x8, STM32F103xB"  在页面【顶部】 y=59
#     ATmega 页眉 "ATmega328P [DATASHEET]"    在页面【底部】 y=738
# 更麻烦的是 ATmega 的【顶部】区域反而是正文（312 个块），
# 按位置一刀切会把正文切掉。
#
# 所以改成按【高频重复】判断：页眉页脚的本质是在几十上百页上
# 重复出现同一句话，正文绝不会。这个判据与排版位置完全无关。
EDGE_TOP_RATIO = 0.10      # 页面高度 10% 以内 -> 算边缘区（统计用）
EDGE_BOTTOM_RATIO = 0.85   # 页面高度 85% 以外 -> 算边缘区（统计用）
TEMPLATE_MIN_COUNT = 5     # 某行在边缘区出现 >= 5 次 -> 判定为页眉页脚模板
TEMPLATE_MIN_LEN = 5       # 太短的行（如纯页码）不参与模板统计

# 整块就是页码 / 图纸编号的形式，如 "104"、"3/115"
PAGE_NUM_RE = re.compile(r"\d{1,4}(/\d{1,4})?")

TABLE_OVERLAP_RATIO = 0.5  # R3：块与表格矩形的重叠面积 / 块面积，超过这个比例就丢弃
MIN_BLOCK_LEN = 12         # R5：短于这个字数的块，需要进一步检查是不是碎片
TOC_DOT_THRESHOLD = 5      # R4：一页里出现多少次 ". . ." 引导点就判定为目录页

# R6：图形页净化。有些页整页是框图/引脚图（如第 11、25 页），上面的文字
#     大多是图内标签。这类页要额外过滤：只保留"像完整句子"的块。
GRAPHICS_PAGE_SHORT_RATIO = 0.6   # 短块占比超过这个值 -> 判定为图形页
# 图内标签的两个特征（实测归纳）：
#   ① 单行且很短，如 "USBDP/CAN_TX"(13)、"ai17351"(7)
#   ② 多行但每行都很短，如引脚排布 "B\nPA12\nPC10\nPC15-\nOSC32_OUT"
# 而小节标题（"General PCB design guidelines" 28 字）和完整句子
# （"This LQFP is a 48-pin, 7 x 7 mm low-profile quad flat package"）要保住。
LABEL_SINGLE_LINE_MAX = 25        # 单行短于这个长度 -> 图内标签
LABEL_MULTI_AVG_LINE_MAX = 20     # 多行且平均行长短于这个值 -> 标签序列

# 章节编号，如 "6.2" / "5.1.7" / "14."（ATmega 是"数字+点"的写法）。
# 带编号的块一定是小节标题，绝不能当标签删。
# 正则 (?:\d+\.)+\d* 的含义：至少出现一次"数字+点"，后面可以再跟数字。
#     "14."    -> 匹配（一次"14."）
#     "6.2"    -> 匹配
#     "5.1.7"  -> 匹配
#     "104"    -> 不匹配（没有点）—— 这是图纸编号，该被当标签处理
SECTION_NUM_RE = re.compile(r"(?:\d+\.)+\d*")


def looks_like_figure_label(text: str) -> bool:
    """
    判断一段文字是不是"图里面的标签"（引脚名、刻度、封装尺寸标注）。

    算法：按行拆开，取【平均行长】跟阈值比。带章节编号的块直接判定为标题。

    为什么用平均行长，而不是中位数或最长行（这两个都试过，都会错）：
      中位数：被"末行很短"拉低。第 12 页的脚注
              "1.\\nWhen the HSI is used as a PLL clock input, the maximum
               system clock frequency that can be achieved is \\n64 MHz."
              行长是 [2, 101, 7]，中位数只有 7，会被误判成标签 —— 但它是正文。
      最长行：被"首行很长"抬高。引脚编号块
              "64 63 62 61 ... 49\\n48\\n47\\n46..." 第一行有 50 字，
              但后面每行只有 2~3 字。用最长行会漏判成正文。
      平均值：上面两种情况都能正确区分 —— 脚注平均 37 字（是正文），
              引脚编号块平均约 4 字（是标签）。

    但平均值单独用也不行，会误杀"编号 + 标题"两行结构的小节标题，
    例如 "6.2 \\nVFQFPN36 package information (ZR)"（平均只有 19 字）。
    所以再加一条：首行是纯章节编号的，一律当标题保留。
    """
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return True

    # 先丢掉"纯符号行"（单独的 "-" / "●" / "•"）。它们是列表符号，不是内容，
    # 留着会把平均行长拉低。ATmega 手册里正文列表就是这种形态：
    #     "●\nTwo independent output compare units\n●\nDouble buffered ..."
    # 不丢掉符号行的话，平均行长只有 18 字，正文列表会被误判成图内标签。
    lines = [ln for ln in lines if not re.fullmatch(r"[^\w\s]{1,3}", ln)]
    if not lines:
        return True

    # 带章节编号的块 = 小节标题，保留
    if SECTION_NUM_RE.fullmatch(lines[0]):
        return False

    avg_len = sum(len(ln) for ln in lines) / len(lines)

    if len(lines) == 1:
        return avg_len < LABEL_SINGLE_LINE_MAX
    return avg_len < LABEL_MULTI_AVG_LINE_MAX

# R5：句子标点。块里只要有这些，就认为它是有意义的句子，不是碎片。
# 关键：必须排除"数字之间的标点"，否则会把下面两种图内标签误判成句子——
#     PA[ 15:0]        <- 位宽写法里的冒号
#     VDD = 2 to 3.6V  <- 数值里的小数点
# 所以加了 (?<!\d)（前面不是数字）和 (?=\s|$)（后面是空格或结尾）两个条件。
# 这样匹配的是"真正的句末标点"，如 "... polynomial." 或 "Note: xxx"。
SENTENCE_PUNCT = re.compile(r"(?<!\d)[.:;，。；：](?=\s|$)")

# R4：目录的引导点，形如 "Parameter conditions . . . . . . . 12"
TOC_DOTS_RE = re.compile(r"\.\s\.\s\.")

# 清洗用：Unicode 特殊字符归一化表
#   \xa0 是不换行空格（PDF 里常用来做缩进，直接删会粘连，换成普通空格）
#   \u2013 是 EN DASH（短横线），\u2212 是数学减号，统一成 ASCII 的 "-"
#   \u2022 是项目符号圆点，统一成 "-"，让列表格式一致
#   \u25cf 是黑色圆点 ●，ATmega 手册用得多（STM32 用的是 \u2022），同样统一
#   \u25aa / \u25a0 是大小方块，少数手册拿来做列表符号
CHAR_MAP = {
    "\xa0": " ",
    "\u2013": "-",
    "\u2212": "-",
    "\u2014": "-",
    "\u2022": "-",
    "\u25cf": "-",
    "\u25aa": "-",
    "\u25a0": "-",
    "\ufb01": "fi",
    "\ufb02": "fl",
}

# 段落换行的判断：以这些开头的行，视为"新的一段"而不是"上一句的延续"
NEW_ITEM_RE = re.compile(r"^(-|\*|\d+\.|\d+\))\s")


# ==================================================================
# 工具函数
# ==================================================================

def line_template(line: str) -> str:
    """
    把一行里的数字统统换成 #，得到"模板"。

    为什么要这样：页眉页脚在不同页上只有数字会变，例如
        "7810D-AVR-01/15 2"  → "7810D-AVR-##/## #"
        "7810D-AVR-01/15 3"  → "7810D-AVR-##/## #"
    换成模板后它们才是同一个东西，才能统计出"这句话重复出现在很多页上"。
    """
    return re.sub(r"\d+", "#", line)


def is_page_number_line(line: str, page_no: int) -> bool:
    """
    判断这一行是不是"当前页的页码"。

    判据不只是"长得像数字"，还要数值上对得上：
        PDF 第 37 页上出现 "37"    -> 是页码
        PDF 第 37 页上出现 "115"   -> 不是页码（可能是别的东西），不删
    这样比单纯删数字安全得多 —— 正文里的数字不会恰好等于页码 ±1。
    """
    m = PAGE_NUM_RE.fullmatch(line)
    if not m:
        return False
    # 注意用 group(0) 取整个匹配；这个正则里的 group(1) 是"(/115)"那个可选组
    head = int(m.group(0).split("/")[0])   # "37/115" 取 37
    return abs(head - page_no) <= 1


def collect_repeated_lines(doc: pymupdf.Document) -> set[str]:
    """
    第一遍扫描：找出"在页面边缘区反复出现"的行，也就是页眉页脚。

    原理：正文内容每页都不同，不会重复；页眉页脚每页都一样，
    必然在几十上百页上出现。所以"重复次数"是比"页面位置"更可靠的判据。

    实测数据（验证过）：
        STM32  "STM32F103x8, STM32F103xB"  在 114 页里出现 100+ 次
        ATmega "ATmega328P [DATASHEET]"    在 294 页里出现 146 次
        ATmega "7810D-AVR-01/15"           在 294 页里出现 146 次
    而正文段落没有一句会重复 5 次以上。

    只统计页面边缘区（上下 10% / 15% 范围），是为了再给一道保险 ——
    即便正文某句话被反复引用，只要不在边缘区就不会被当成页眉。
    """
    counter: Counter = Counter()
    for page in doc:
        h = page.rect.height
        for b in page.get_text("blocks"):
            if b[6] != 0 or not b[4].strip():
                continue
            # 只统计边缘区的块
            if not (b[3] < h * EDGE_TOP_RATIO or b[1] > h * EDGE_BOTTOM_RATIO):
                continue
            for ln in b[4].split("\n"):
                ln = clean_chars(ln).strip()
                # 太短的行（纯页码）和纯数字行不参与，它们走 is_page_number_line
                if len(ln) < TEMPLATE_MIN_LEN or not re.search(r"[A-Za-z]", ln):
                    continue
                counter[line_template(ln)] += 1

    return {t for t, c in counter.items() if c >= TEMPLATE_MIN_COUNT}


def clean_chars(text: str) -> str:
    """把 PDF 里的特殊 Unicode 字符换成普通字符。"""
    for bad, good in CHAR_MAP.items():
        text = text.replace(bad, good)
    # 连续 3 个以上空白压成 1 个空格（PDF 排版常有连续空格）
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text


def merge_lines(text: str) -> str:
    """
    把 PDF 提取出来的"多行"接成正常的段落。

    为什么需要：PDF 是按"视觉行"存字的，一句话排版成 3 行，提取出来就是 3 行。
    直接入库会让"这句话被切成三截"，检索时匹配不上。

    规则：默认把下一行接到上一行后面（用空格连接）；
         遇到以 "-" "•" "1." 开头的行，认为是新的一段，保留换行。
    """
    lines = [ln.strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]          # 丢掉空行
    if not lines:
        return ""

    out: list[str] = [lines[0]]
    for ln in lines[1:]:
        if NEW_ITEM_RE.match(ln):
            out.append("\n" + ln)               # 新的列表项，保留换行
        else:
            prev = out[-1]
            # 上一行以连字符结尾，说明是单词被折断了（如 "charact-" + "eristic"）
            if prev.endswith("-") and not prev.endswith(" -"):
                out[-1] = prev[:-1] + ln
            else:
                out[-1] = prev + " " + ln
    return "".join(out)


def rect_overlap_ratio(block_rect: tuple, table_rect: tuple) -> float:
    """算一个文本块被表格矩形覆盖的面积比例（0~1）。"""
    bx0, by0, bx1, by1 = block_rect
    tx0, ty0, tx1, ty1 = table_rect

    # 两个矩形相交部分的宽和高（取 0 和正值，负数说明不相交）
    ox = max(0.0, min(bx1, tx1) - max(bx0, tx0))
    oy = max(0.0, min(by1, ty1) - max(by0, ty0))

    block_area = (bx1 - bx0) * (by1 - by0)
    if block_area <= 0:
        return 0.0
    return (ox * oy) / block_area


# ==================================================================
# 主流程
# ==================================================================

def extract_page(page: pymupdf.Page, doc_title: str,
                 templates: set[str] | None = None,
                 dropped: list | None = None) -> tuple[str, dict]:
    """
    处理一页，返回 (清洗后的正文, 统计信息)。

    pymupdf 的 page.get_text("blocks") 返回的是列表，
    每个元素形如 (x0, y0, x1, y1, 文本, 块编号, 块类型)：
        - 前 4 个数是矩形坐标
        - 第 5 个（下标 4）是文字内容
        - 第 7 个（下标 6）是类型：0 = 文本块，1 = 图片块
    我们只要文本块，所以过滤 b[6] == 0。

    templates 参数：由 collect_repeated_lines() 提前算好的「页眉页脚模板行集合」。
    dropped 参数：传入一个列表，函数会把被剔掉的块追加进去，方便事后审计。
    """
    templates = templates or set()
    stats = {"total": 0, "header": 0, "footer": 0, "table": 0,
             "fragment": 0, "graphics": 0, "kept": 0}

    # 先拿到这一页所有表格的矩形（复用 P0 第 1 步的 find_tables）
    table_rects = [t.bbox for t in page.find_tables().tables]

    blocks = [b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
    stats["total"] = len(blocks)

    # 判断这一页是不是"图形页"：短块（少于 16 字）占比超过 60%。
    # 依据：实测 22 页满足此条件，全是框图/引脚图（第 11、22~27、34、36 页等）。
    page_texts = [clean_chars(b[4]).strip() for b in blocks]
    short_ratio = (sum(1 for t in page_texts if len(t) < 16) / len(page_texts)
                   if page_texts else 0.0)
    is_graphics_page = short_ratio > GRAPHICS_PAGE_SHORT_RATIO

    # R4：先判断整页是不是目录页
    page_text = page.get_text("text")
    if len(TOC_DOTS_RE.findall(page_text)) >= TOC_DOT_THRESHOLD:
        stats["toc_page"] = True
        return "", stats

    kept_texts: list[str] = []
    page_no = page.number + 1          # 页码从 1 开始
    page_h = page.rect.height          # 这一页的高度，用来算边缘区

    for b in blocks:
        x0, y0, x1, y1, raw = b[0], b[1], b[2], b[3], b[4]
        text = clean_chars(raw).strip()

        # R1/R2-a 整块就是页码的话直接丢
        #   形如 "104"（STM32 的图纸编号）、"37/115"、"50"，且位于页面边缘。
        #   加边缘区条件是防止误删正文表格里的数字单元格。
        if PAGE_NUM_RE.fullmatch(text) and (
                y1 < page_h * EDGE_TOP_RATIO or y0 > page_h * EDGE_BOTTOM_RATIO):
            stats["footer"] += 1
            continue

        # R3 表格区
        if any(rect_overlap_ratio((x0, y0, x1, y1), tr) > TABLE_OVERLAP_RATIO
               for tr in table_rects):
            stats["table"] += 1
            continue

        # R1/R2-b 逐行清洗：把混在正文块里的页眉页脚行剥掉。
        #   页眉常和正文挤在同一个块里，例如 STM32 的
        #       "Description\nSTM32F103x8, STM32F103xB\n<真正的正文…>"
        #   所以必须按行处理，不能整块丢。
        raw_lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        lines = [
            ln for ln in raw_lines
            if line_template(ln) not in templates          # 不是页眉页脚模板行
            and not is_page_number_line(ln, page_no)       # 不是当前页码
            and ln != doc_title                            # 不是文档名
        ]
        if len(lines) != len(raw_lines):
            stats["header"] += 1
            text = "\n".join(lines)
        if not lines:
            continue

        # R5 碎片：短且没有句子标点
        if len(text) < MIN_BLOCK_LEN and not SENTENCE_PUNCT.search(text):
            stats["fragment"] += 1
            if dropped is not None:
                dropped.append((page_no, "R5碎片", text))
            continue

        # R6（只在图形页生效）：淘汰图内标签
        #   实测：图形页上 `USBDP/CAN_TX`、`B PA12 PC10 PC15OSC32_OUT` 这类
        #   图内文字长度会超过 12，R5 拦不住，所以在图形页上再按
        #   "行数 + 行长"判断一次。
        #   注意：这里刻意【不】用"是否含标点"做判据 —— 因为框图里
        #   `PA[ 15:0]`（位宽冒号）、`VDD = 2 to 3.6V`（小数点）都含标点，
        #   用标点判断会全部漏掉；反过来也【不能】一刀切按长度删，
        #   否则会误杀图形页上的小节标题（第 77 页 "General PCB design
        #   guidelines"）和完整句子（第 98 页 "This LQFP is a 48-pin, ..."）。
        if is_graphics_page and looks_like_figure_label(text):
            stats["graphics"] += 1
            if dropped is not None:
                dropped.append((page_no, "R6图标签", text))
            continue

        merged = merge_lines(text)
        if merged:
            kept_texts.append(merged)
            stats["kept"] += 1

    return "\n\n".join(kept_texts), stats


def main() -> None:
    parser = argparse.ArgumentParser(description="提取 PDF 正文并清洗")
    parser.add_argument("--pdf", default="datasheets/STM32F103C8_Datasheet.pdf",
                        help="PDF 路径（相对项目根目录）")
    parser.add_argument("--out", default="data/text_v1",
                        help="输出目录（相对项目根目录）")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parents[1]
    pdf_path = base_dir / args.pdf
    out_dir = base_dir / args.out / pdf_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(pdf_path)
    # 文档标题（页眉里反复出现的那个名字），用来从正文块里剔除
    doc_title = pdf_path.stem.replace("_Datasheet", "").replace("_", " ")

    print("=" * 66)
    print(f"正文提取：{pdf_path.name}  共 {len(doc)} 页")
    print("=" * 66)

    # ---------- 第一遍扫描：识别页眉页脚 ----------
    templates = collect_repeated_lines(doc)
    print(f"识别出 {len(templates)} 种页眉页脚模板（在边缘区重复出现 "
          f"≥{TEMPLATE_MIN_COUNT} 次）：")
    for t in sorted(templates):
        print(f"    {t}")
    print()

    grand = {"total": 0, "header": 0, "footer": 0, "table": 0,
             "fragment": 0, "graphics": 0, "kept": 0}
    toc_pages: list[int] = []
    empty_pages: list[int] = []
    all_dropped: list[tuple[int, str, str]] = []   # (页码, 规则, 内容)
    written = 0

    for pno in range(len(doc)):
        page = doc[pno]
        text, stats = extract_page(page, doc_title, templates, all_dropped)

        for k in grand:
            grand[k] += stats.get(k, 0)

        if stats.get("toc_page"):
            toc_pages.append(pno + 1)
            continue

        if not text.strip():
            empty_pages.append(pno + 1)
            continue

        md = (f"[来源] {pdf_path.name} 第 {pno + 1} 页 正文\n"
              f"[页码] {pno + 1}\n\n{text}\n")
        (out_dir / f"page_{pno + 1:03d}.md").write_text(md, encoding="utf-8")
        written += 1

    # ---------------- 剔除清单（可审计） ----------------
    # 把 R5/R6 剔掉的每一条都写成文件，方便人工复核有没有冤枉的。
    # 这是上一轮踩过的坑：光靠"我觉得规则对"不算数，必须能回查。
    lines = ["# 被剔除的文本块清单（R5 碎片 / R6 图内标签）", ""]
    for p, rule, txt in all_dropped:
        lines.append(f"- [第 {p} 页] [{rule}] [{len(txt)}字] {txt!r}")
    (out_dir / "_dropped.md").write_text("\n".join(lines), encoding="utf-8")

    # 报警：剔除内容里长度 >= 30 的，很可能是被误杀的正文
    long_dropped = [(p, r, t) for p, r, t in all_dropped if len(t) >= 30]

    # ---------------- 统计报告 ----------------
    print()
    print("=" * 66)
    print("提取结果")
    print("=" * 66)
    print(f"  文本块总数      : {grand['total']}")
    print(f"  剔除 · 页眉     : {grand['header']}")
    print(f"  剔除 · 页脚页码 : {grand['footer']}")
    print(f"  剔除 · 表格区域 : {grand['table']}")
    print(f"  剔除 · 图形碎片 : {grand['fragment']}")
    print(f"  剔除 · 图内标签 : {grand['graphics']}  (仅图形页生效)")
    print(f"  保留的正文块    : {grand['kept']}  "
          f"({grand['kept'] / grand['total'] * 100:.1f}%)")
    print()
    print(f"  整页丢弃 · 目录页 : {len(toc_pages)} 页 {toc_pages}")
    print(f"  整页丢弃 · 无正文 : {len(empty_pages)} 页")
    print(f"  输出文件          : {written} 个")
    print(f"  输出目录          : {out_dir}")

    total_chars = sum(len((out_dir / f.name).read_text(encoding="utf-8"))
                      for f in out_dir.glob("page_*.md"))
    print(f"  正文总字符数      : {total_chars}")
    print(f"  剔除清单          : {out_dir / '_dropped.md'}")

    # ---------------- 误杀报警 ----------------
    print()
    print("=" * 66)
    print(f"误杀审查：被剔除内容中长度 >= 30 的（共 {len(long_dropped)} 条，需人工确认）")
    print("=" * 66)
    if not long_dropped:
        print("  无 —— 没有长内容被剔除，不存在误杀风险")
    else:
        for p, rule, txt in long_dropped[:15]:
            print(f"  第 {p:>3} 页 [{rule}] {txt[:80]!r}")
        if len(long_dropped) > 15:
            print(f"  ...（其余 {len(long_dropped) - 15} 条见 _dropped.md）")


if __name__ == "__main__":
    main()
