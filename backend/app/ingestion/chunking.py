# -*- coding: utf-8 -*-
"""
P1 第 1 步：把 P0 的清洗产物切成检索用的小块（新线路的唯一切块脚本）
====================================================================

输入：
    data/text_v2/<pdf_stem>/page_*.md     正文页（app/ingestion/text.py 产出）
    data/tables_v5/<pdf_stem>/page_*.md   表格页（app/ingestion/tables.py 产出）

输出：
    data/chunks_v2/<pdf_stem>/chunks.jsonl   每行一个 JSON，供 app/ingestion/indexer.py 入库
    data/chunks_v2/<pdf_stem>/_report.md     人读的统计报告，便于审计

────────────────────────────────────────────────────────────────
2026-09-29 说明：这个脚本原来是"哑切块"，现在升级成和旧线路同等质量
────────────────────────────────────────────────────────────────
旧线路（backend/legacy/p1_1_chunk.py）切块切得好，但读的是旧目录；
新线路（本脚本）原来只是把正文按 400 字粗暴切断，缺三样东西：

  1. 【上下文前缀】旧线路每块开头会贴一句
       [STM32F103C8_Datasheet.pdf 第 37 页 · 正文 · 6.2 Absolute maximum ratings]
     因为切出来的块本身常常缺主语（一堆 "The maximum frequency is 72 MHz"），
     贴上"这是哪份手册、第几页、哪一节"之后，向量才表达得准。
  2. 【按小节切】遇到新小节标题就收尾当前块，保证一块只讲一件事，
     不会把"ADC"和"定时器"混在一起。
  3. 【表格跨页合并 + 超长拆片】表 5（引脚定义）横跨第 30~33 页，
     不拼回来，"PB10 引脚"只能检索到一页的碎片；
     超长的表按行拆，但每一片都重复贴表头，否则只有数据没有列名。

这三样现在全部搬进来了。旧线路的脚本已归档到 backend/legacy/。
"""

import argparse
import json
import re
import statistics
from pathlib import Path

try:
    import pymupdf                    # 只用来扫描矢量图形（生成指针块）
except ImportError:                   # pragma: no cover
    import fitz as pymupdf


# ---------- 项目根目录 ----------
from backend.app.config import ROOT

# ---------- 中文清洗 ----------
# 切块是"入库前的最后一道"，这里再洗一遍做兜底：
# 即使上游（text.py / tables.py）哪一步漏了，也还有一次机会。
from backend.app.ingestion.cn_clean import (
    clean_cn_text,
    is_han,
    merge_wrapped_lines,
)


# ==================================================================
# 可调参数（都集中在这里，方便实验）
# ==================================================================

# 正文块的目标长度（字符）。**中英文必须分开**，因为同样的"字符数"
# 承载的信息量差好几倍：
#     英文 500 字符 ≈ 80 个词  ≈ 讲清一个技术点
#     中文 500 字符 = 500 个汉字，信息量是英文的 3~4 倍，容易把两件事混一块
#     中文 350 字  ≈ 正好一个完整的技术点
# 实测 CH32F103 手册正文平均句长约 40 字，350 字约 9 句，是一个合理的"一件事"。
TEXT_TARGET_CHARS_EN = 500
TEXT_TARGET_CHARS_CN = 350
TEXT_TARGET_CHARS = TEXT_TARGET_CHARS_EN     # 兼容旧引用

# 判定"这段是中文"的汉字占比门槛。
# 0.3 而不是 0.5：技术手册常常中英混排（"CH32F103 系列基于 32 位 ARM Cortex-M3 内核"），
# 汉字占比会被型号和术语稀释掉，门槛太高会判成英文。
CJK_RATIO_THRESHOLD = 0.30

# 触发"换节切块"的最小块长。
# 为什么需要它：小节标题判据是启发式的，数据手册里到处是一行一行的短条目
# （"Memories - 64 or 128 Kbytes of Flash memory" 之类），
# 如果每遇到一行短条目就切一刀，会切出一大堆 50 字符的小碎块
# （实测不加这道闸门会切出 578 块、平均只有 358 字符，碎块对检索是负面的）。
# 攒够这个长度才真换节，块长才落回目标值附近。
TEXT_MIN_CHARS = 200
TABLE_MAX_CHARS = 2600       # 表格块上限。超过就按行拆分，每片重复带表头

# 表格**索引文本**（自描述句）的字符上限。
#
# ⚠️ 这个常量是 2026-10-03 建库失败后补上的，不要删。
#
#   为什么单看 TABLE_MAX_CHARS 不够：
#       自描述句是"每个数据点一行"，数据点多的表，索引文本会比 markdown
#       长出好几倍。实测：
#           表3-7 睡眠模式电流消耗   markdown 1831 字符 / 索引文本 4840 字符
#           表2-1 引脚定义          markdown 1788 字符 / 索引文本 3777 字符
#       这两张表因为 markdown 没超 2600，被判定为"够短、不用切"，
#       于是索引文本带着 4840 字符直接送去 embedding ——
#       超过智谱 embedding-3 单条 3072 token 的上限，接口返回
#       400（code 1210 参数错误），**整轮建库失败**，前面几批白花钱。
#
#   为什么取 1500：
#       中文技术文本大致 1 字符 ≈ 1 token，1500 字符约 1500 token，
#       只到 3072 上限的一半，留足余量（英文/符号的 token 化效率不同，
#       留一倍余量才不会被个别块反咬一口）。
TABLE_INDEX_MAX_CHARS = 1500

# ---------- 父块（给 LLM 看的更大上下文）----------
# 用户的要求："召回 10 个块，打分取最高的 3 块，
#              把答案、3 个最高分的块、以及它们所在的大块，一起打包给 LLM"
# 这里的"大块"就是父块：一个父块 = 一个小节 或 一张完整的表。
# 子块用来**检索**（小而准），父块用来**给模型读**（大而全）。
PARENT_MAX_CHARS = 4000      # 父块内容上限，超了就截断（防止撑爆上下文窗口）

# ---------- 矢量图形（当指针用，不当内容）----------
# 用户的要求："矢量框图当指针用，不当内容"
# 原因：框图里的文字是矢量绘制的，没有文字层可抽取，
#       硬当内容处理只会得到一堆残缺标签（实测第 11 页框图里就漏出
#       `SUPPLY | Col2` 这种碎片，一路混进过向量库）。
#       正确做法是生成一个"指针块"：告诉检索方"这一页有图，需要看图请翻 PDF"，
#       同时明确声明"本块不含图形内容"，避免模型凭空编造图里的信息。
FIGURE_MIN_AREA_RATIO = 0.06   # 图形区域面积占整页超过这个比例才算"框图"
FIGURE_TABLE_OVERLAP = 0.5     # 与表格区域重叠超过这个比例 -> 其实是表格，不算图

SOURCE_PREFIX = "[来源]"
PAGE_PREFIX = "[页码]"
TITLE_PREFIX = "[标题]"
TYPE_PREFIX = "[类型]"

# 小节编号，如 "2.3 Overview" / "2.3.1 Arm Cortex-M3 core" / "A.1 xxx"
#
# 为什么编号后面要加 (?=[A-Z\u4e00-\u9fff]) —— 要求标题以【大写字母或中文】开头。
#   小数点在技术文档里到处都是，光看"数字.数字 + 空格 + 文字"会把一堆东西
#   当成章节标题。实测踩到的假标题：
#       "0.1 μF"                电容值
#       "0.8 mm pitch, ..."     封装尺寸标注
#       "1.55 1.16"             表格漏出来的碎片
#   而真正的小节标题一定是以大写字母开头的英文短语（或中文），
#   所以加这一个前瞻断言就能把它们干净地分开。
SECTION_NUM_RE = re.compile(
    r"^([0-9]+(?:\.[0-9]+)+|[A-Z]\.\d+)\s+(?=[A-Z\u4e00-\u9fff])(\S.*)$"
)

# 兜底：纯数字行（只由数字、点、空格、斜杠、正负号组成）绝不可能是标题。
PURE_NUMERIC_RE = re.compile(r"^[\d.\s/+-]+$")

# "Table 5. xxx (continued)" 这类跨页续表标记
CONTINUED_RE = re.compile(r"\(\s*continued\s*\)", re.IGNORECASE)

# 表 / 图的题注（中英文都要认）。
#   英文手册：  "Table 6. Voltage characteristics"
#   中文手册：  "表1-1 CH32F103x 产品资源分配"   ← 实测中文这里没有空格
# 只写 (Table|Figure) 的话，中文手册的题注一行都认不出来。
CAPTION_RE = re.compile(r"^(?:Table|Figure|表|图)\s*\d+", re.IGNORECASE)

# markdown 表格的分隔线 |---|---|
SEP_ROW_RE = re.compile(r"\|[\s\-:|]+\|")

# 表格文件里的「数据点」段标记（由 app/ingestion/tables.py 写出）
DATA_POINT_PREFIX = "[数据点]"


# ==================================================================
# 通用小工具
# ==================================================================

def cjk_ratio(text: str) -> float:
    """汉字占全部字符的比例，用来判断"这段算中文还是英文"。"""
    if not text:
        return 0.0
    return sum(1 for ch in text if is_han(ch)) / len(text)


def target_chars_for(text: str) -> int:
    """
    按语言返回正文块的目标长度。

    为什么要分：中文 500 字和英文 500 字符根本不是一个量级的信息 ——
    中文没有空格，一个字就是一个词素；英文 500 字符只有 80 来个词。
    用同一个数字切，中文块会明显偏大（容易把两件事混进一块），
    英文块则偏小（一句话被切断）。

    判据是汉字占比，不是"有没有汉字"：技术手册全是中英混排，
    "CH32F103 系列基于 32 位 ARM Cortex-M3 内核" 里汉字只占一半多，
    所以要按比例判。
    """
    if cjk_ratio(text) > CJK_RATIO_THRESHOLD:
        return TEXT_TARGET_CHARS_CN
    return TEXT_TARGET_CHARS_EN


def to_rel(path: Path) -> str:
    """把绝对路径转成相对项目根目录的写法，打印用；不在项目里就原样返回。"""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def read_page_file(path: Path) -> tuple[dict, str]:
    """
    读一个 page_*.md，拆成 (元数据字典, 正文)。

    文件长这样：
        [来源] STM32F103C8_Datasheet.pdf
        [页码] 37
        [标题] 第 37 页正文
        [类型] text

        正文第一段...
    """
    meta: dict[str, str] = {}
    body_lines: list[str] = []
    in_body = False

    for ln in path.read_text(encoding="utf-8").splitlines():
        if not in_body:
            if ln.startswith(SOURCE_PREFIX):
                meta["source"] = ln[len(SOURCE_PREFIX):].strip()
                continue
            if ln.startswith(PAGE_PREFIX):
                meta["page"] = ln[len(PAGE_PREFIX):].strip()
                continue
            if ln.startswith(TITLE_PREFIX):
                meta["title"] = ln[len(TITLE_PREFIX):].strip()
                continue
            if ln.startswith(TYPE_PREFIX):
                meta["type"] = ln[len(TYPE_PREFIX):].strip()
                continue
            if not ln.strip():
                in_body = True      # 空行 = 元数据结束，正文开始
                continue
        body_lines.append(ln)

    return meta, "\n".join(body_lines).strip()


def table_rows(md: str) -> list[str]:
    """
    返回一张表的**所有行**（不含 |---|---| 分隔线），第 0 行是表头。

    和 split_markdown_rows 的区别：这个不拆表头/数据，原样给全部行。
    跨页合并必须用这个 —— 见下面 merge_cross_pages 的说明。
    """
    rows = [ln.strip() for ln in md.splitlines() if ln.strip().startswith("|")]
    return [r for r in rows if not SEP_ROW_RE.fullmatch(r)]


def split_markdown_rows(md: str) -> tuple[str, list[str]]:
    """
    把一张 markdown 表格拆成 (表头行, 数据行)。

    会自动丢掉 |---|---| 这条分隔线（它只是给人看的渲染用，
    对模型没意义，而且留着会干扰"取第一行当表头"的逻辑）。
    """
    rows = table_rows(md)
    if not rows:
        return "", []
    return rows[0], rows[1:]


def _row_key(row: str) -> str:
    """比对两行是不是同一行时的归一化：只看有内容的单元格，忽略空格差异。"""
    cells = [c.strip() for c in row.strip("|").split("|")]
    return "|".join(c for c in cells if c)


def normalize_title(title: str) -> str:
    """
    把表格标题洗成一个"身份 key"，用来判断两页上的表是不是同一张。

    为什么要洗：
        跨页续表在第 31 页印的是 "Table 5. xxx (continued)"，第 30 页却是
        "Table 5. xxx" —— 字符串不一样，但是同一张表。
        另外 P0 解析下标时可能引入空格，如 "Medium - density"。
        所以统一：去掉 (continued)、去掉所有非字母数字的字符。
    """
    t = CONTINUED_RE.sub("", title)
    t = re.sub(r"[^0-9A-Za-z]", "", t)
    return t


# ==================================================================
# 一、表格切块
# ==================================================================

def parse_table_file(path: Path) -> list[dict]:
    """
    解析一个表格 page_XXX.md，返回里面所有表的列表。

    一个文件可能含多张表，靠 [来源] 行分隔：
        [来源] STM32F103C8_Datasheet.pdf
        [页码] 37
        [标题] Table 6. Voltage characteristics
        [类型] table

        | Symbol | ... |
        ...
        [来源] STM32F103C8_Datasheet.pdf
        [页码] 37
        [标题] Table 7. Current characteristics
        ...
        [数据点]
        - CH32F103 C6T6 · 芯片引脚数 = 48
        ...

    [数据点] 段是 2026-10-03 新增的（由 app/ingestion/tables.py 写出）。
    它是**索引文本**的来源：markdown 表格里那个孤立的 "48"，
    向量和 BM25 都看不出它属于哪个型号；
    自描述句 "CH32F103 C6T6 · 芯片引脚数 = 48" 才能被检索命中。
    """
    blocks: list[dict] = []
    cur: dict | None = None
    in_records = False          # 是否已经进入 [数据点] 段

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()

        if line.startswith(SOURCE_PREFIX):
            if cur is not None:
                blocks.append(cur)
            cur = {
                "source": line[len(SOURCE_PREFIX):].strip(),
                "page": 0,
                "title": "",
                "lines": [],
                "records": [],
            }
            in_records = False
        elif cur is None:
            continue
        elif line.startswith(PAGE_PREFIX):
            digits = re.sub(r"\D", "", line)
            cur["page"] = int(digits) if digits else 0
        elif line.startswith(TITLE_PREFIX):
            cur["title"] = line[len(TITLE_PREFIX):].strip()
        elif line.startswith(TYPE_PREFIX):
            continue                      # [类型] table 只是标记，不进正文
        elif line.startswith(DATA_POINT_PREFIX):
            in_records = True             # 从这里开始，后面的行都是数据点
        elif in_records:
            item = line.strip()
            if item.startswith("-"):
                item = item[1:].strip()
            if item:
                cur["records"].append(item)
        else:
            cur["lines"].append(line)

    if cur is not None:
        blocks.append(cur)

    for b in blocks:
        b["md"] = "\n".join(b["lines"]).strip()

    return blocks


def merge_cross_pages(blocks: list[dict]) -> list[dict]:
    """
    把跨页的续表拼回一张。

    判定：相邻两块标题洗完之后完全相同（且标题非空）-> 同一张表。
    实测中这个判据很安全：不同表的编号不同，标题天然不同。

    ⚠️ 这里踩过一个坑（2026-09-29 QA 复核时抓出来的）：
       合并必须用 table_rows() 拿"全部行"，不能拆成 (表头, 数据) 再拼数据部分。
       旧写法 `prev["md"] = 数据 + 数据` 把第一页的**表头整个弄丢了**，
       更糟的是：合并后 prev 的第一行变成了数据行，
       下一次合并时它又被当成"表头"丢掉 —— 于是每多合并一页就白丢一行数据。
       实测 Table 5（第 28-33 页，合并 5 次）丢了 4 行、Table 64 丢了 6 行。

       现在的做法：
         1. 用 table_rows() 取回"表头 + 数据"全部行，拼完仍保留第一页那份表头；
         2. 续页重复印的表头，只有**确认和首页表头一样**才删掉；
            不比对就无脑删第一行，遇到没重复表头的续页会白丢一行数据。
    """
    merged: list[dict] = []

    for b in blocks:
        key = normalize_title(b["title"])

        # 标题为空 -> 不敢合并（怕把几张互不相干的表粘成一块）
        if key and merged and normalize_title(merged[-1]["title"]) == key:
            prev = merged[-1]
            prev_rows = table_rows(prev["md"])
            cur_rows = table_rows(b["md"])

            # 续页重复表头 -> 和首页表头一致才丢
            if (prev_rows and cur_rows
                    and _row_key(cur_rows[0]) == _row_key(prev_rows[0])):
                cur_rows = cur_rows[1:]

            prev["md"] = "\n".join(prev_rows + cur_rows)
            # 数据点也要一起合并。跨页续表会在每一页重复写一遍 [数据点]，
            # 所以必须去重，否则同一句 "CH32F103 C6T6 · 芯片引脚数 = 48"
            # 会出现 N 次，把索引文本撑得又长又偏。
            # dict.fromkeys 去重同时保留原有顺序（set 会打乱）。
            merged_records = list(dict.fromkeys(
                prev.get("records", []) + b.get("records", [])
            ))
            prev["records"] = merged_records
            prev["pages"].append(b["page"])
            continue

        new = dict(b)
        new["pages"] = [b["page"]]
        merged.append(new)

    return merged


def build_table_index_text(title: str, records: list[str]) -> str:
    """
    表格块的**索引文本** —— 拿去向量化和 BM25 的那份文字。

    为什么索引文本必须和展示文本分开：

        展示文本（content，给人 / 模型看全貌）：
            | 芯片引脚数 | 48 | 48 | 48 | 64 |
            | 闪存（字节） | 32K | 64K | 64K | 64K |

        索引文本（index_text，拿去做检索）：
            CH32F103 C6T6 · 芯片引脚数 = 48
            CH32F103 C8T6 · 芯片引脚数 = 48
            CH32F103 C6T6 · 闪存（字节） = 32K
            ...

    如果用展示文本去做检索会怎样（这是改造前的老问题）：
        "48" 是完全孤立的 —— 向量只能表达"这张表里有个 48"，
        BM25 也只能匹配到 "48" 这个 token，谁也不知道它属于哪个型号。
        用户问"CH32F103C6T6 的引脚数是多少"，模型只能瞎猜。

    换成自描述句之后，每个数值都绑着自己的列头（型号）和行头（指标名），
    "CH32F103 C6T6""芯片引脚数" 都是完整可匹配的串。

    返回空串表示这张表没有数据点（走了旧的 to_markdown 路径），
    调用方应该退回用 content 当索引文本。
    """
    if not records:
        return ""
    head = f"表格标题: {title}\n" if title else ""
    return head + "\n".join(records)


def split_records_for_pieces(records: list[str],
                             row_counts: list[int]) -> list[list[str]]:
    """把一张表的数据点，按各分片包含的数据行数分给对应的分片。

    参数：
        records     : 整张表的全部数据点（自描述句），扁平列表
        row_counts  : 每个分片各包含多少行 markdown 数据行，
                      例如 [6, 6, 5] 表示切成 3 片，分别有 6、6、5 行

    返回：
        [[第1片的数据点...], [第2片的数据点...], ...]

    【为什么是"按行数比例分"，而不是"精确对齐"】

        精确对齐需要知道"这一行 markdown 对应哪几条数据点"。
        但一行 markdown 里有几个数据列，就会生成几条数据点，
        这个行组信息在 P0 阶段（tables.py 写 [数据点] 段）就摊平丢掉了，
        找回来得重跑整条 P0 链路（表格提取那一步很慢，而且有回归风险）。
        所以这里按行数比例分配 —— 是最小改动下的合理近似。

    【为什么近似不影响最终答案】

        分片都来自**同一张表**。检索命中任意一片之后，
        都会通过"父块放大"把整张表的原文一起送给模型
        （见 retrieval/hybrid.py 的 _pack 和 vectorstore/parents.json）。
        所以就算某条数据点落到了邻片，答案也不会缺 ——
        最多是那一片的索引文本多捎带了一条附近的数据点，
        对检索精度的影响可以忽略。

    边界情况：
        - records 为空 -> 每个分片都返回空列表
        - row_counts 全为 0 -> 全部数据点给第一片（总不能丢）
        - **最后一片兜底收尾**：四舍五入会留余数，最后一个分片直接
          把剩下的全拿走，保证不会漏掉任何一条数据点
    """
    if not records:
        return [[] for _ in row_counts]

    total_rows = sum(row_counts)
    if total_rows <= 0:
        return [list(records)] + [[] for _ in row_counts[1:]]

    out: list[list[str]] = []
    pos = 0
    for i, n_rows in enumerate(row_counts):
        if i == len(row_counts) - 1:
            out.append(list(records[pos:]))     # 最后一片收尾，保证不丢
            break
        # 按行数占比分配；至少给 1 条（这一片有行，却一条数据点都不给，不合理）
        share = round(len(records) * n_rows / total_rows)
        if n_rows and share < 1:
            share = 1
        out.append(list(records[pos:pos + share]))
        pos += share

    return out


def make_table_chunks(blocks: list[dict], doc_name: str) -> tuple[list[dict], list[str]]:
    """把合并后的表变成 chunk。超长的表按行拆，每片重复贴表头。"""
    chunks: list[dict] = []
    notes: list[str] = []

    for b in blocks:
        title = b["title"] or "(无标题)"
        pages = b["pages"]
        page_label = (
            f"第 {pages[0]} 页"
            if len(pages) == 1
            else f"第 {pages[0]}-{pages[-1]} 页（跨页续表，已合并）"
        )

        header, body = split_markdown_rows(b["md"])
        if not body:
            # 不静默丢：写进报告，方便事后核对（本项目的一条硬规矩）
            notes.append(
                f"- ⚠️ 《{title}》（{page_label}）没有数据行（只有表头/空行），已跳过"
            )
            continue

        whole = "\n".join([header] + body) if header else "\n".join(body)

        # 整张表的全部数据点（自描述句）。空列表表示这张表走的是旧的
        # to_markdown 路径、没有数据点 —— 那时索引文本退回 content。
        all_records: list[str] = b.get("records", [])
        index_text_full = build_table_index_text(title, all_records)

        # ---- 分片：同时盯住 content 和 index_text 两个长度（2026-10-03 修正）----
        #
        # 旧版只看 content 长度，漏掉 index_text —— 后果是建库直接失败：
        #   实测表 3-7 的 content 只有 1831 字符（低于 2600 上限，判定"够短不切"），
        #   但它的 index_text 有 4840 字符。自描述句是"每个数据点一行"，
        #   数据点多的表，索引文本会比 markdown 长出好几倍。
        #   4840 字符超过智谱 embedding-3 单条 3072 token 上限，
        #   接口返回 400（code 1210），**整轮建库失败** —— 前面几批的
        #   token 已经花掉，向量却全丢。
        #
        # 所以：只有两个长度都不超，才算"够短"；装桶时也要同时盯两个预算。
        #
        # 每行的索引成本怎么估：
        #   精确值要知道"这行 markdown 对应哪几条数据点"，但行组信息在 P0
        #   阶段就被摊平了（找回它要重跑整条 P0 链路）。这里按行数**平摊**
        #   总字符数来估 —— 不精确，但足以把每片压进安全区间；
        #   而片与片同属一张表，命中任意一片都会经"父块放大"拿到整表原文，
        #   所以这点误差传不到最终答案。
        rec_chars = sum(len(r) + 1 for r in all_records)
        n_rows = max(len(body), 1)
        rec_chars_per_row = rec_chars / n_rows

        if (len(whole) <= TABLE_MAX_CHARS
                and len(index_text_full) <= TABLE_INDEX_MAX_CHARS):
            buckets: list[list[str]] = [body]
        else:
            # 超长 -> 按行拆分，每片都带上原始表头，缺了表头数据就读不懂了。
            #
            # 为什么是"顺着装桶"而不是"按行数均分"：
            #   按行数均分（旧线路的做法）保证不了每片的长度 ——
            #   表格各行的长度差得很远，均分后照样会出现超大片
            #   （实测 Table 64 修订历史表就是，远超上限）。
            #   改成顺着一行行往下装，装到"再加这一行就要超"就封口，
            #   这样每片都贴着上限、又不会超；只有"单独一行本身就超限"时
            #   才没办法 —— 那一种由 indexer 的兜底截断保证不会把建库搞崩。
            buckets = []
            cur: list[str] = []
            cur_c = len(header)          # 当前桶的 markdown 字符数
            cur_i = 0.0                  # 当前桶的索引文本字符数（估算值）
            for row in body:
                over_content = cur and cur_c + len(row) + 1 > TABLE_MAX_CHARS
                over_index = cur and cur_i + rec_chars_per_row > TABLE_INDEX_MAX_CHARS
                if over_content or over_index:
                    buckets.append(cur)
                    cur = []
                    cur_c = len(header)
                    cur_i = 0.0
                cur.append(row)
                cur_c += len(row) + 1
                cur_i += rec_chars_per_row
            if cur:
                buckets.append(cur)

            notes.append(
                f"- 《{title}》（{page_label}）共 {len(body)} 行："
                f"content {len(whole)} 字符、索引文本 {len(index_text_full)} 字符，"
                f"超过上限（{TABLE_MAX_CHARS} / {TABLE_INDEX_MAX_CHARS}），"
                f"已切成 {len(buckets)} 片（每片都重复带表头）"
            )

        pieces = ["\n".join([header] + bk) if header else "\n".join(bk)
                  for bk in buckets]

        # 索引文本也跟着分片 —— 不能再让所有分片共用同一份完整的：
        #   ① 共用就是上面那个 400 的成因（每片都带着 4840 字符的超长索引文本）
        #   ② 共用还让几片的索引文本一模一样，检索时同时命中、同分，
        #      白白占掉多个候选位，等于浪费了召回数
        index_pieces = split_records_for_pieces(
            all_records, [len(bk) for bk in buckets])

        # 父块键：同一张表的所有分片归到同一个父块，
        # 这样检索命中第 2 片时，也能把整张表一起送给模型
        parent_key = f"table::{doc_name}::{title}::{pages[0]}"

        for i, piece in enumerate(pieces, 1):
            # 这一片自己的数据点（越界时给空列表，索引文本会退回 content）
            recs_i = index_pieces[i - 1] if i - 1 < len(index_pieces) else []
            index_text = build_table_index_text(title, recs_i)

            part_note = f"（第 {i}/{len(pieces)} 部分）" if len(pieces) > 1 else ""
            content = (
                f"[{doc_name} {page_label} · 表格{part_note}]\n"
                f"表格标题: {title}\n\n"
                f"{piece}"
            )
            chunks.append({
                "content": content,
                "index_text": index_text,      # 空串 -> 落盘时退回 content
                "parent_key": parent_key,
                "source": doc_name,
                "type": "table",
                "title": title,
                "page_start": pages[0],
                "page_end": pages[-1],
                "part": f"{i}/{len(pieces)}",
                "n_chars": len(content),
            })

        if len(pages) > 1:
            notes.append(f"- 《{title}》横跨原 {pages} 页，已合并为完整一张")

    return chunks, notes


# ==================================================================
# 二、正文切块
# ==================================================================

def is_heading(p: str) -> bool:
    """
    判断一个段落是不是"小节标题"。

    标题的特征（实测归纳）：
        - 短（一般不超过 90 字符）
        - 独占一段（没有换行）
        - 多数带编号，如 "2.3.1 Arm Cortex-M3 core"
    反过来，正文段落一般较长、且以句号结尾。
    """
    if len(p) > 90 or "\n" in p:
        return False
    # 带编号、且不是纯数字行 -> 是小节标题
    if SECTION_NUM_RE.match(p) and not PURE_NUMERIC_RE.fullmatch(p):
        return True
    # 表 / 图的题注（中英都要认，中文手册写的是"表1-1"）
    if CAPTION_RE.match(p):
        return True
    if p.endswith((".", ",", ";", ":")):
        return False
    # 没有编号的标题只有"短"才算。为什么要把上限从 70 收到 60、并限制词数：
    #   实测 "Memories - 64 or 128 Kbytes of Flash memory, 20 Kbytes of SRAM"
    #   这类规格条目有 60 多字，会被误判成小节标题，
    #   结果正文被切成一堆碎块（平均块长只有目标值的一半）。
    return len(p) <= 60 and len(p.split()) <= 12


def update_headings(p: str, h1: str, h2: str) -> tuple[str, str]:
    """
    维护"我当前读到哪一节了"。

    编号里有几个点就代表几级：
        "6 Electrical characteristics"     -> 一级，更新 h1
        "6.2 Absolute maximum ratings"     -> 二级，更新 h2
        "6.2.1 xxx"                        -> 三级，也当作 h2（更细的上下文）
    """
    m = SECTION_NUM_RE.match(p)
    if not m or PURE_NUMERIC_RE.fullmatch(p):
        return h1, h2
    num = m.group(1)
    level = num.count(".") + 1
    title = f"{num} {m.group(2)}"
    if level <= 2:
        return title, ""
    return h1, title


def build_text_chunks(text_dir: Path, doc_name: str) -> list[dict]:
    """
    把正文页切成一堆小块（中文 350 字 / 英文 500 字，按语言自适应）。

    三条关键规则（直接决定检索质量）：
      1. 遇到新的小节标题 -> 立刻收尾当前块。
      2. 每块开头贴上下文前缀：[手册名 第 N 页 · 正文 · 这一节的标题路径]
      3. 块长按语言自适应（见 target_chars_for 的说明）——
         中文 500 字塞进了英文 500 字符三倍多的信息，
         不区分的话中文块会把两件事混在一起。

    2026-10-03 补充：
      - 正文做一次兜底清洗（汉字间空格、不可见字符）
      - 每块带上 parent_key，同一个小节的所有块归到一个父块，
        检索命中其中一块时可以把整节一起送给模型（解决"切碎了看不到全貌"）
    """
    chunks: list[dict] = []
    files = sorted(text_dir.glob("page_*.md"))
    h1 = h2 = ""       # 跨页保留的章节上下文

    for f in files:
        meta, body = read_page_file(f)
        page = int(meta.get("page") or 0)

        # 兜底清洗：上游（app/ingestion/text.py）已经洗过一遍，这里再洗一次防漏网。
        # 只影响汉字之间的空格和不可见字符，不会动段落结构（不碰空行）。
        body = clean_cn_text(body)

        paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]

        buf: list[str] = []

        def flush(cur_h1: str, cur_h2: str) -> None:
            """把攒够的内容打包成一块。"""
            if not buf:
                return
            path = " > ".join(x for x in (cur_h1, cur_h2) if x)
            head = f"[{doc_name} 第 {page} 页 · 正文"
            if path:
                head += f" · {path}"
            head += "]"
            content = f"{head}\n\n" + "\n\n".join(buf)

            # 同一个小节的块归到同一个父块。
            # 没有章节标题的页（如"概述"页）用页码当分组，避免整本手册
            # 的无标题段落粘成一个巨型父块。
            group = path or f"第{page}页"

            chunks.append({
                "content": content,
                "index_text": "",      # 正文块的索引文本就是 content 本身（落盘时回填）
                "parent_key": f"text::{doc_name}::{group}",
                "source": doc_name,
                "type": "text",
                "title": path,
                "page_start": page,
                "page_end": page,
                "part": "1/1",
                "n_chars": len(content),
            })
            buf.clear()

        for p in paragraphs:
            if is_heading(p):
                # 换节边界。只有"已经攒够 TEXT_MIN_CHARS"时才真切一刀，
                # 否则继续攒 —— 不然连续几行短条目会切出一堆几十字的小碎块。
                if sum(len(x) + 2 for x in buf) >= TEXT_MIN_CHARS:
                    flush(h1, h2)
                h1, h2 = update_headings(p, h1, h2)
                # 判定成标题的这一段，仍然放进新块的正文里。
                # 为什么这么做：标题判据是启发式的（"短、不带标点"），
                # 万一把一条正文短句误判成标题，不留下来就等于**静默删掉**它。
                # 留着最坏也只是重复一次章节名，绝不会丢内容 —— 覆盖优先于干净。
                buf.append(p)
                continue

            buf.append(p)
            # 块长目标按当前攒的内容动态取（中文 350 / 英文 500）
            if sum(len(x) + 2 for x in buf) >= target_chars_for("\n".join(buf)):
                flush(h1, h2)

        flush(h1, h2)

    return chunks


# ==================================================================
# 三、矢量图形：只登记"这里有图"，不提取图的内容
# ==================================================================

def rect_overlap_area(a, b) -> float:
    """
    两个矩形（或 pymupdf.Rect）的重叠面积。

    同时接受 (x0,y0,x1,y1) 元组和 pymupdf.Rect —— 因为表格 bbox 是元组，
    而 cluster_drawings() 返回的是 Rect，两种都要能吃。
    """
    if hasattr(a, "x0"):
        ax0, ay0, ax1, ay1 = a.x0, a.y0, a.x1, a.y1
    else:
        ax0, ay0, ax1, ay1 = a
    if hasattr(b, "x0"):
        bx0, by0, bx1, by1 = b.x0, b.y0, b.x1, b.y1
    else:
        bx0, by0, bx1, by1 = b

    ox = min(ax1, bx1) - max(ax0, bx0)
    oy = min(ay1, by1) - max(ay0, by0)
    if ox <= 0 or oy <= 0:
        return 0.0
    return ox * oy


def build_figure_chunks(pdf_path: Path, doc_name: str
                        ) -> tuple[list[dict], list[str]]:
    """
    为每页的「矢量图形」生成**指针块**。

    ══ 为什么是"指针"而不是"内容"（用户明确要求）══

    矢量框图（引脚图、功能框图、时序图）里的文字是用线条和路径**画**出来的，
    没有可提取的文字层。硬当内容处理只有两种下场：

        ① 抽不出来 —— 白费力气；
        ② 抽出残缺碎片 —— 实测第 11 页的框图漏出过 `SUPPLY | Col2`
           这种半截东西，还混进过向量库，变成"一本正经的噪声"。

    所以正确做法是只登记"这里有图"这个事实，同时**明确声明本块不含图形内容**。
    这样模型知道的是"该去看原图"，而不是"可以从这里编一个引脚定义出来"。

    ══ 怎么判断哪些是图 ══

    1. page.cluster_drawings() 把矢量元素聚成块
    2. 面积超过整页 6% 的算"大块"
    3. 排除跟表格区域高度重叠的 —— 表格框线本身也是矢量！
       实测第 2 页表格聚出来的块是 437×363，不排除就会被当成"图"。

    实测 CH32F103（29 页）的结果：
        第 12~15 页  聚出 503×668 这类整栏大块   -> 真框图 ✅
        第 2 页      聚出 437×363               -> 其实是表格，已排除 ✅

    返回 (指针块列表, 说明行列表)。
    """
    chunks: list[dict] = []
    notes: list[str] = []

    doc = pymupdf.open(pdf_path)
    try:
        for pno in range(len(doc)):
            page = doc[pno]
            page_no = pno + 1

            try:
                clusters = page.cluster_drawings()
            except Exception:
                continue
            if not clusters:
                continue

            page_area = page.rect.width * page.rect.height

            # 本页的表格区域（用来排除"其实是表格"的矢量块）
            try:
                table_rects = [tuple(t.bbox) for t in page.find_tables().tables]
            except Exception:
                table_rects = []

            figures = []
            for c in clusters:
                area = c.width * c.height
                if area <= page_area * FIGURE_MIN_AREA_RATIO:
                    continue
                covered = max(
                    (rect_overlap_area(c, tr) / area for tr in table_rects),
                    default=0.0,
                )
                if covered > FIGURE_TABLE_OVERLAP:
                    continue        # 这是表格，不是图
                figures.append(c)

            if not figures:
                continue

            rect_desc = "、".join(
                f"({int(f.x0)},{int(f.y0)})-({int(f.x1)},{int(f.y1)})"
                for f in figures[:4]
            )

            # 措辞里"本块不包含任何图形内容"这句是**必须的**：
            # 不给这句，模型会拿"第 12 页有引脚图"这个事实去编引脚定义。
            content = (
                f"[{doc_name} 第 {page_no} 页 · 图形]\n\n"
                f"本页含 {len(figures)} 幅矢量图形（框图 / 引脚图 / 时序图），"
                f"区域：{rect_desc}。\n"
                f"这些图形是矢量绘制，没有可提取的文字层，"
                f"因此本块不包含任何图形内容，仅作为出处指针。\n"
                f"如需图形信息（引脚排布、模块连接关系等），"
                f"请查阅 {doc_name} 第 {page_no} 页的原图。"
            )

            chunks.append({
                "content": content,
                "index_text": "",      # 落盘时回填 content
                "parent_key": f"figure::{doc_name}::第{page_no}页",
                "source": doc_name,
                "type": "figure",
                "title": f"第 {page_no} 页图形",
                "page_start": page_no,
                "page_end": page_no,
                "part": "1/1",
                "n_chars": len(content),
            })
            notes.append(
                f"- 第 {page_no} 页：登记 {len(figures)} 幅矢量图形（生成指针块，"
                f"不含图形内容）"
            )
    finally:
        doc.close()

    return chunks, notes


# ==================================================================
# 四、父块：把子块按"节 / 表"聚合，给模型更大的上下文
# ==================================================================

def build_parents(chunks: list[dict], stem: str) -> list[dict]:
    """
    按 parent_key 把子块聚成父块，并给每个子块回填 parent_id。

    用户的要求：
        "召回 10 个块，打分取最高的 3 块，
         把答案、3 个最高分的块、以及它们所在的大块，一起打包给 LLM"

    这里的"大块"就是父块。为什么要它：

        子块为了检索准确必须切小（中文 350 字），但 350 字经常只有半句话的
        上下文。比如表1-1 有 80 个数据点、被切成好几片，
        命中第 2 片时模型只看得到中间几行，不知道这是
        "CH32F103x 产品资源分配"这张表的一部分，也不知道上面还有表头。
        把父块（整张表 / 整节）一起给它，模型才有完整视野。

    父块的三种来源（靠 parent_key 前缀区分）：
        table::  同一张表的所有分片
        text::   同一个小节的所有正文块
        figure:: 单个图形指针块（自己就是父块）
    """
    groups: dict[str, list[dict]] = {}
    for c in chunks:
        key = c.get("parent_key") or c["id"]
        groups.setdefault(key, []).append(c)

    parents: list[dict] = []
    for i, (_key, cs) in enumerate(groups.items(), 1):
        pid = f"{stem}_p{i:04d}"
        for c in cs:
            c["parent_id"] = pid

        content = "\n\n".join(c["content"] for c in cs)
        truncated = len(content) > PARENT_MAX_CHARS
        if truncated:
            content = content[:PARENT_MAX_CHARS] + "\n…（本节过长，已截断）"

        parents.append({
            "parent_id": pid,
            "content": content,
            "type": cs[0]["type"],
            "source": cs[0]["source"],
            "title": cs[0]["title"],
            "page_start": min(c["page_start"] for c in cs),
            "page_end": max(c["page_end"] for c in cs),
            "child_ids": [c["id"] for c in cs],
            "n_children": len(cs),
            "n_chars": len(content),
            "truncated": truncated,
        })

    return parents


# ==================================================================
# 主流程
# ==================================================================

def main() -> None:
    ap = argparse.ArgumentParser(description="切块：把 P0 清洗产物切成检索用的小块")
    ap.add_argument("--pdf", default="datasheets/STM32F103C8_Datasheet.pdf",
                    help="PDF 路径（相对项目根目录），用来推导输入输出目录名")
    ap.add_argument("--out", default=None,
                    help="输出目录，默认 data/chunks_v2/<pdf_stem>")
    args = ap.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.is_absolute():
        pdf_path = ROOT / pdf_path
    stem = pdf_path.stem
    doc_name = pdf_path.name

    text_dir = ROOT / "data" / "text_v2" / stem
    table_dir = ROOT / "data" / "tables_v5" / stem

    if not text_dir.exists() or not table_dir.exists():
        print(f"[错误] 找不到 P0 的产物目录：")
        print(f"       {to_rel(text_dir)}  {'(存在)' if text_dir.exists() else '(缺失)'}")
        print(f"       {to_rel(table_dir)}  {'(存在)' if table_dir.exists() else '(缺失)'}")
        print("       请先运行：")
        print("         python -m backend.app.ingestion.tables")
        print("         python -m backend.app.ingestion.text")
        return

    if args.out:
        out_dir = Path(args.out)
        if not out_dir.is_absolute():
            out_dir = ROOT / out_dir
    else:
        out_dir = ROOT / "data" / "chunks_v2" / stem
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 66)
    print(f"切块：{doc_name}")
    print("=" * 66)

    # ---- 表格 ----
    blocks: list[dict] = []
    for f in sorted(table_dir.glob("page_*.md")):
        blocks.extend(parse_table_file(f))

    # 按 (页码, 出现顺序) 排序，保证跨页合并时顺序正确
    raw_table_count = len(blocks)
    merged = merge_cross_pages(blocks)
    table_chunks, notes = make_table_chunks(merged, doc_name)

    # ---- 正文 ----
    text_chunks = build_text_chunks(text_dir, doc_name)

    # ---- 矢量图形：只登记"这里有图"，不提取图的内容 ----
    figure_chunks, fig_notes = build_figure_chunks(pdf_path, doc_name)

    # ---- 合并、编号、排序 ----
    chunks = table_chunks + text_chunks + figure_chunks
    chunks.sort(key=lambda c: (c["page_start"], 0 if c["type"] == "table" else 1))
    for i, c in enumerate(chunks, 1):
        c["id"] = f"{stem}_c{i:04d}"
        # 索引文本兜底：
        #   表格块 -> 自描述句（在 make_table_chunks 里设好）
        #   正文块 / 图形块 -> 就是 content 本身
        if not c.get("index_text"):
            c["index_text"] = c["content"]

    # ---- 父块（子块按"节 / 表"聚合，供检索后放大上下文用）----
    parents = build_parents(chunks, stem)

    # ---- 落盘 ----
    jsonl_path = out_dir / "chunks.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as fp:
        for c in chunks:
            fp.write(json.dumps(c, ensure_ascii=False) + "\n")

    parents_path = out_dir / "parents.jsonl"
    with parents_path.open("w", encoding="utf-8") as fp:
        for p in parents:
            fp.write(json.dumps(p, ensure_ascii=False) + "\n")

    # ---- 报告 ----
    lens = [c["n_chars"] for c in chunks]
    total_chars = sum(lens)
    toks = int(total_chars / 3.5)

    report = [
        f"# 切块报告：{doc_name}",
        "",
        "## 总览",
        "",
        f"- 表格块：**{len(table_chunks)}**（原始 {raw_table_count} 张表，"
        f"跨页合并后 {len(merged)} 张）",
        f"- 正文块：**{len(text_chunks)}**",
        f"- 图形指针块：**{len(figure_chunks)}**（只在有矢量框图的页生成，"
        f"内容是指针不是图形）",
        f"- 合计子块：**{len(chunks)} 块**",
        f"- 父块：**{len(parents)}**（同节 / 同表的子块聚合，供放大上下文）",
        f"- 总字符数：{total_chars:,}（约 {toks:,} token）",
    ]
    if lens:
        report.append(
            f"- 单块长度：最短 {min(lens)}，最长 {max(lens)}，"
            f"平均 {int(statistics.mean(lens))}，中位数 {int(statistics.median(lens))}"
        )
    report += [
        "",
        "## 处理记录",
        "",
    ]
    report.extend(notes + fig_notes if (notes or fig_notes)
                  else ["（无需跨页合并、拆表或图形登记）"])
    report += ["", "## 最长的 5 块（确认没有异常巨大）", ""]
    for c in sorted(chunks, key=lambda x: -x["n_chars"])[:5]:
        preview = c["content"][:80].replace("\n", " ")
        report.append(f"- `{c['id']}` {c['n_chars']} 字符 [{c['type']}] {preview}...")

    (out_dir / "_report.md").write_text("\n".join(report), encoding="utf-8")

    print(f"  表格张数（原始）      : {raw_table_count}")
    print(f"  表格张数（跨页合并后）: {len(merged)}")
    print(f"  表格块                : {len(table_chunks)}")
    print(f"  正文块                : {len(text_chunks)}")
    print(f"  图形指针块            : {len(figure_chunks)}")
    print(f"  合计子块              : {len(chunks)} 块")
    print(f"  父块                  : {len(parents)}")
    if lens:
        print(f"  总字符数              : {total_chars:,}")
        print(f"  单块 最短/平均/最长   : "
              f"{min(lens)} / {int(statistics.mean(lens))} / {max(lens)}")
    print()
    print(f"  已写出: {to_rel(jsonl_path)}")
    print(f"  已写出: {to_rel(parents_path)}")
    print(f"  已写出: {to_rel(out_dir / '_report.md')}")


if __name__ == "__main__":
    main()
