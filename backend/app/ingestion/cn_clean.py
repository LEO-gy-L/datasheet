# -*- coding: utf-8 -*-
"""
中文文本清洗（全项目共用底座）
================================

解决的问题全部来自实测（CH32F103_Datasheet_CN.pdf，29 页），不是推测：

【问题 1】换行被插空格 —— 这是最要命的一个，也是"定时器检索不到"的根因
    PDF 是按"视觉行"存字的。一句话在纸面上排成 3 行，提取出来就是 3 行。
    旧的合并逻辑是 `prev + " " + ln` —— 对英文是对的（单词之间本来就该有空格），
    对中文是灾难：
        定 / 时 / 器   ->   "定 时 器"
    检索"定时器"永远匹配不上，因为库里存的是带空格的"定 时 器"。
    实测该手册有 168 处汉字被换行断开。

    → smart_join() 按"两端是不是都是中文"决定加不加空格。
      中文接中文：直接连（定+时 = 定时）
      其他情况：  加空格（The + maximum = "The maximum"）

【问题 2】汉字之间本来就有空格
    部分 PDF 排版会在汉字间塞空格（实测 4 处，如 "第1 章 规格信息"）。
    这种空格对检索毫无意义，删掉更干净。
    → strip_spaces_between_han()
    ⚠️ 只删"汉字 + 空格 + 汉字"，绝不动 "CH32F103 C6T6" 这种字母数字之间的空格。

【问题 3】不可见字符
    \xa0（不换行空格）、\u3000（全角空格）、\u200b（零宽空格）、\ufeff（BOM）
    这些字符肉眼看不见，但会让字符串比对悄悄失败 —— 用户敲的空格和 PDF 里的不是同一个码位。
    → strip_invisible()

被谁用：
    app/ingestion/text.py      正文提取（merge_lines 里调用 smart_join）
    app/ingestion/tables.py    表格单元格提取
    app/ingestion/chunking.py  切块前做最后一道兜底
    app/ingestion/table_struct.py  表头合并（CH32F103 + C6T6 -> CH32F103 C6T6）

设计原则：**只做无损清洗**。任何会丢内容的操作都不做 ——
宁可留下一个多余的空格，也不能把"定时器"洗成"定器"。
"""
from __future__ import annotations

import re

# ==================================================================
# 一、字符分类：哪些字符属于"中文语境"
# ==================================================================

# 汉字本体。含：
#   \u4e00-\u9fff  基本汉字（最常用，覆盖 99% 的现代中文）
#   \u3400-\u4dbf  扩展 A 区（生僻字）
#   \uf900-\ufaff  兼容汉字（台湾/香港用字）
_HAN_RANGES: tuple[tuple[int, int], ...] = (
    (0x4E00, 0x9FFF),
    (0x3400, 0x4DBF),
    (0xF900, 0xFAFF),
)

# 中文标点。这些字符跟汉字连写时同样不该插空格：
#   "定时器，" + "并" -> "定时器，并"（而不是 "定时器， 并"）
_CN_PUNCT: frozenset[str] = frozenset(
    "、。〃々〆〇〈〉《》「」『』【】〔〕〖〗"
    "，．；：？！…—～·ˉ¨〝〞‘’“”"
    "（）［］｛｝〔〕"
    "０１２３４５６７８９ＡＢＣ"   # 全角数字 / 字母
)


def is_han(ch: str) -> bool:
    """判断单个字符是不是汉字。"""
    if not ch:
        return False
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in _HAN_RANGES)


def is_cn_punct(ch: str) -> bool:
    """判断单个字符是不是中文标点（全角标点）。"""
    return bool(ch) and ch in _CN_PUNCT


def is_cn_char(ch: str) -> bool:
    """
    中文语境字符 = 汉字 或 中文标点。

    拼接时用它判断"该不该加空格"：
        中文语境 + 中文语境 -> 不加空格
        其他任何组合        -> 加空格
    """
    return is_han(ch) or is_cn_punct(ch)


# ==================================================================
# 二、智能拼接：中文之间不加空格
# ==================================================================

def smart_join(prev: str, cur: str) -> str:
    """
    把两段文字接起来，按内容决定要不要垫一个空格。

    这是整个模块最重要的一行逻辑，直接决定"定时器"能不能被检索到。

    规则（就三条，按顺序判）：

        prev 末尾       cur 开头       结果            例子
        ─────────────────────────────────────────────────────────
        中文            中文           直接连          "定" + "时器"   -> "定时器"
        以连字符结尾     任意           去掉连字符再连   "charact-" + "eristic" -> "characteristic"
        其他            其他           垫一个空格       "The" + "maximum"      -> "The maximum"

    为什么"其他情况"要保守地加空格：
        漏加空格会把两个英文单词粘成一个（"in the" -> "inthe"），
        这个词在检索时彻底消失；多加一个空格最坏只是显示难看一点。
        所以拿不准的时候，一律加空格。
    """
    if not prev:
        return cur
    if not cur:
        return prev

    # prev 已经以空白结尾 -> 不再重复添加
    if prev[-1].isspace():
        return prev + cur

    # 连字符折行："charact-" + "eristic" -> "characteristic"
    # 注意排除 " - "（破折号前后本来就有空格的写法不算折行）
    if prev.endswith("-") and not prev.endswith(" -"):
        return prev[:-1] + cur

    # 核心判定：两端都是中文语境字符 -> 直接连，不插空格
    if is_cn_char(prev[-1]) and is_cn_char(cur[0]):
        return prev + cur

    return prev + " " + cur


# ==================================================================
# 三、清洗：不可见字符 / 汉字间空格 / <br>
# ==================================================================

# 各种"看不见但会坏事"的字符，统一换成普通空格或直接删掉
INVISIBLE_MAP: dict[str, str] = {
    "\xa0": " ",      # 不换行空格（PDF 排版最常用它）
    "\u1680": " ",    # Ogham 空格
    "\u2000": " ",    # En quad
    "\u2001": " ",
    "\u2002": " ",
    "\u2003": " ",
    "\u2004": " ",
    "\u2005": " ",
    "\u2006": " ",
    "\u2007": " ",
    "\u2008": " ",
    "\u2009": " ",    # Thin space
    "\u200a": " ",
    "\u202f": " ",    # Narrow no-break space
    "\u205f": " ",
    "\u3000": " ",    # 全角空格（中文排版里常用来缩进）
    "\u200b": "",     # 零宽空格 —— 直接删
    "\u200c": "",     # 零宽非连接符
    "\u200d": "",     # 零宽连接符
    "\u2060": "",     # word joiner
    "\ufeff": "",     # BOM
}


def strip_invisible(text: str) -> str:
    """
    把不可见字符换成普通空格（或删掉），再把连续空格压成一个。

    为什么连全角空格 \u3000 也要动：
        中文排版里两个全角空格表示"首行缩进"，它在检索时没有任何意义，
        但会让"　　定时器"和用户敲的"定时器"变成两个不同的字符串。
    """
    for old, new in INVISIBLE_MAP.items():
        if old in text:
            text = text.replace(old, new)
    # 连续空白（含制表符）压成一个普通空格，但**不动换行符** ——
    # 换行是段落边界，删了就把两段话粘成一段了
    text = re.sub(r"[ \t\f\v]{2,}", " ", text)
    return text


def strip_spaces_between_han(text: str) -> str:
    """
    删掉"汉字 + 空格 + 汉字"中间的空格。

        "定 时 器"        -> "定时器"
        "第1 章 规格信息"  -> "第1章规格信息"

    实测的 4 种情况（都要处理）：
        "定 时 器"        -> "定时器"        汉字 + 空格 + 汉字
        "第1 章 规格信息"  -> "第1章规格信息"   数字 + 空格 + 汉字（章节号）
        "引脚数 48"        -> "引脚数48"       汉字 + 空格 + 数字
        "GPIO 端口数"      -> "GPIO 端口数"    ★ 保留！左侧是英文字母

    ⚠️ 三条安全边界，都是为了"不误伤"：

        ① **空格两侧不能有英文字母**，且**至少一侧是汉字**。
           为什么把英文字母排除在外（这条最关键）：
             如果允许删 "GPIO 端口数" -> "GPIO端口数"，那么 BM25 分词时
             "GPIO端口数" 会变成一个整体 token，用户搜 "GPIO" 反而命中不了。
             粘连造成的损失比多一个空格大得多，所以有字母就一律不删。

        ② 允许中间有多个空格，但**不允许有换行** ——
           换行由 merge_wrapped_lines() 专门处理，两者职责不重叠。

        ③ 用 while 循环反复替换，直到没有变化为止 ——
           因为 "甲 乙 丙" 一次正则只能吃掉一个空格（正则匹配不重叠），
           单次 sub 会留下 "甲乙 丙" 这种半成品。
    """

    def _repl(m: re.Match[str]) -> str:
        left, right = m.group(1), m.group(2)
        # 至少一侧是汉字才删。
        # 两侧都不是汉字（例如 "- 0.3" 的 "-" 和 "0"）原样保留 ——
        # 数值表的负号跟数字之间不能粘死。
        if is_han(left) or is_han(right):
            return left + right
        return m.group(0)

    # [^\sA-Za-z] = 非空白、非英文字母（汉字、数字、标点都算）
    pattern = re.compile(r"([^\sA-Za-z])[ \t]+([^\sA-Za-z])")

    prev = None
    while prev != text:
        prev = text
        text = pattern.sub(_repl, text)
    return text


# <br> / <br/> / <BR > 等各种写法
BR_RE = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
# 其他残留的 HTML 标签（表格转换偶尔留下 <b> <span> 之类）
HTML_TAG_RE = re.compile(r"</?\s*(?:b|i|u|em|strong|span|div|p|font)\b[^>]*>", re.IGNORECASE)


def unwrap_br(text: str, sep: str = " ") -> str:
    """
    处理 <br> 标签。

    为什么要参数化 sep：
        同一个 <br>，在不同位置含义完全不同 ——
        在**表格单元格**里它是"这一格有两行"（如斜线表头的
        "产品型号<br>资源差异" 两行分别对应列和行），要保留成可读的分隔；
        在**正文**里它只是排版换行，直接连起来更好。
    """
    return BR_RE.sub(sep, text)


def strip_html_tags(text: str) -> str:
    """去掉残留的 HTML 标签（不含 <br>，那个由 unwrap_br 单独处理）。"""
    return HTML_TAG_RE.sub("", text)


# ==================================================================
# 四、段落合并：把"视觉行"接回正常段落
# ==================================================================

def merge_wrapped_lines(text: str, new_item_re: re.Pattern[str] | None = None) -> str:
    """
    把 PDF 提取出的多行接成正常段落。

    和 app/ingestion/text.py 原来的 merge_lines() 唯一区别：
        拼接时用 smart_join()，**中文之间不再插空格**。
        原来那一版用的是 `prev + " " + ln`，正是"定 时 器"的来源。

    参数：
        new_item_re  以它开头的行会被当作"新的一段"，保留换行不合并。
                     传 app/ingestion/text.py 里的 NEW_ITEM_RE 即可
                     （匹配 "- "、"* "、"1. "、"1) " 这些列表项开头）。
                     不传则所有行都往下合并。
    """
    lines = [ln.strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]
    if not lines:
        return ""

    out: list[str] = [lines[0]]
    for ln in lines[1:]:
        # 列表项开头 -> 新的一段，保留换行
        if new_item_re is not None and new_item_re.match(ln):
            out.append("\n" + ln)
            continue
        out[-1] = smart_join(out[-1], ln)

    return "".join(out)


# ==================================================================
# 五、对外总入口
# ==================================================================

def clean_cn_text(text: str, *, br_sep: str = "\n") -> str:
    """
    中文文本清洗总入口，按固定顺序执行（顺序不能调换）。

    顺序为什么是这个：
        1. 先去不可见字符 —— 不然 \\xa0 会被后面的"空格判定"当成普通空格，
           而实际上它是"不换行空格"，语义不同，先归一化最安全。
        2. 再处理 <br>。
        3. 去残留的 HTML 标签。
        4. 然后删汉字周围的空格。
        5. 最后统一空白 —— 兜底把前几步可能产生的连续空格压掉。

    ⚠️ br_sep 默认是**换行符**而不是空格 —— 这一点踩过坑：
       最初写成把 <br> 换成空格，结果 "产品型号<br>资源差异"
       先变成 "产品型号 资源差异"，**紧接着被第 4 步当成
       汉字间空格给删掉了**，最后得到 "产品型号资源差异"，
       两个标签粘成一个词，斜线表头的语义全丢。
       换成换行符之后，第 4 步的空格规则碰不到它，
       换行会一直保留到调用方，由调用方决定怎么处理（正文合并 / 表格换成 " / "）。

    ⚠️ 这个函数**不做行合并**。行合并是 merge_wrapped_lines() 的职责，
       而它需要知道"哪些行是列表项"，那个上下文只有调用方（text.py）才有。
       混在一起会把段落结构搞乱。
    """
    text = strip_invisible(text)
    text = unwrap_br(text, br_sep)
    text = strip_html_tags(text)
    text = strip_spaces_between_han(text)
    # 再压一次连续空格（前面替换可能产生 "a  b"）
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text


def clean_cell_text(text: str) -> str:
    """
    专门给**表格单元格**用的清洗。

    和 clean_cn_text 的区别只有一处：<br> 换出来的换行最终变成 " / "。
    为什么是 " / "：斜线表头 "产品型号<br>资源差异" 是上下两个标签，
    换成空格会得到"产品型号 资源差异"（读起来像一个短语，语义丢了），
    换成 " / " 才保留"这是两个不同的东西"这层信息。

    执行顺序：先按通用规则洗（此时 <br> 已变成换行），再决定换行怎么处理。

    ★ 换行怎么处理，要分两种情况（这一点实测踩过坑）：

      情况 A：竖排表头，每个换行分隔的是一个单字
          "定\\n时\\n器"        -> "定时器"          （不是 "定 / 时 / 器"！）
          "通\\n信\\n接\\n口"    -> "通信接口"
          这是中文 PDF 里竖排标题的标准排版：为了塞进窄列，
          "定时器"三个字被竖着排成三行。拆成 "定 / 时 / 器"
          会让检索"定时器"彻底失效。

      情况 B：真正的多行内容，每段是完整的词
          "产品型号\\n资源差异"  -> "产品型号 / 资源差异"
          这是斜线表头：上半格和下半格是两个不同的标签，
          必须保留"这是两个东西"的信息，不能粘成一个词。

      判据：**过半数的片段只有一个字 -> 判定为竖排，直接拼接**。
      这个判据两边都不会误伤：A 情况 3/3 是单字，B 情况 0/2 是单字。
    """
    t = clean_cn_text(text)                         # 内部把 <br> 变成换行符
    parts = [p.strip() for p in t.split("\n") if p.strip()]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]

    single_char = sum(1 for p in parts if len(p) == 1)
    if single_char * 2 >= len(parts):               # 过半数是单字
        return "".join(parts)                       # 竖排 -> 直接拼

    return " / ".join(parts)                        # 多行内容 -> 用 / 分隔


# ==================================================================
# 自测（在项目根目录跑：python -m backend.app.ingestion.cn_clean）
# ==================================================================

def _self_test() -> None:
    """跑一遍实测用例，确认清洗结果符合预期。"""
    cases: list[tuple[str, str, str]] = [
        # (说明, 输入, 期望输出)
        # ---- 汉字被换行断开（实测 168 处，最主要的问题）----
        ("汉字被换行断开", "定\n时\n器", "定时器"),
        ("真实句子跨行", "可编程电\n器(PVD)", "可编程电器(PVD)"),
        ("汉字间已有空格", "定 时 器", "定时器"),
        ("章节标题里的空格", "第1 章 规格信息", "第1章规格信息"),
        ("汉字接数字", "引脚数 48", "引脚数48"),

        # ---- 不能误伤的情况（这几条比上面更重要）----
        ("英文单词不该粘", "The maximum", "The maximum"),
        ("英文之间换行", "The\nmaximum rating", "The maximum rating"),
        ("型号之间的空格要保留", "CH32F103 C6T6", "CH32F103 C6T6"),
        ("★字母+空格+汉字不能粘", "GPIO 端口数", "GPIO 端口数"),
        ("★负号与数字不能粘", "VDD - 0.3", "VDD - 0.3"),

        # ---- 不可见字符 ----
        ("不换行空格", "定\xa0时\xa0器", "定时器"),
        ("零宽空格", "定\u200b时\u200b器", "定时器"),
        ("全角空格", "定\u3000时\u3000器", "定时器"),

        # ---- 连字符折行 ----
        ("连字符折行", "charact-\neristic", "characteristic"),
    ]

    print("=" * 70)
    print("cn_clean 自测")
    print("=" * 70)
    ok = 0
    for desc, raw, want in cases:
        got = merge_wrapped_lines(clean_cn_text(raw))
        flag = "✅" if got == want else "❌"
        if got == want:
            ok += 1
        print(f"  {flag} {desc}")
        if got != want:
            print(f"       输入: {raw!r}")
            print(f"       得到: {got!r}")
            print(f"       期望: {want!r}")

    # cell 版本单独测（<br> -> " / "）
    got = clean_cell_text("产品型号<br>资源差异")
    flag = "✅" if got == "产品型号 / 资源差异" else "❌"
    print(f"  {flag} 单元格版 br 处理")
    if got == "产品型号 / 资源差异":
        ok += 1
    else:
        print(f"       得到: {got!r}")

    total = len(cases) + 1
    print(f"\n  通过 {ok}/{total}")
    print("=" * 70)


if __name__ == "__main__":
    _self_test()
