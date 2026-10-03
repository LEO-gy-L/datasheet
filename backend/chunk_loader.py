# -*- coding: utf-8 -*-
"""
P1 第 1 步：把 P0 的清洗产物切成检索用的小块（新线路的唯一切块脚本）
====================================================================

输入：
    data/text_v2/<pdf_stem>/page_*.md     正文页（p0_2_extract_text.py 产出）
    data/tables_v5/<pdf_stem>/page_*.md   表格页（p0_1_extract_tables.py 产出）

输出：
    data/chunks_v2/<pdf_stem>/chunks.jsonl   每行一个 JSON，供 p1_2_index.py 入库
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


# ---------- 项目根目录 ----------
ROOT = Path(__file__).resolve().parents[1]


# ==================================================================
# 可调参数（都集中在这里，方便实验）
# ==================================================================

TEXT_TARGET_CHARS = 500      # 正文块的目标长度（字符）。够讲清一件事，又不至于太杂
# 触发"换节切块"的最小块长。
# 为什么需要它：小节标题判据是启发式的，数据手册里到处是一行一行的短条目
# （"Memories - 64 or 128 Kbytes of Flash memory" 之类），
# 如果每遇到一行短条目就切一刀，会切出一大堆 50 字符的小碎块
# （实测不加这道闸门会切出 578 块、平均只有 358 字符，碎块对检索是负面的）。
# 攒够 200 字符才真换节，块长才落回 500 左右的目标。
TEXT_MIN_CHARS = 200
TABLE_MAX_CHARS = 2600       # 表格块上限。超过就按行拆分，每片重复带表头

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

# markdown 表格的分隔线 |---|---|
SEP_ROW_RE = re.compile(r"\|[\s\-:|]+\|")


# ==================================================================
# 通用小工具
# ==================================================================

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
    """
    blocks: list[dict] = []
    cur: dict | None = None

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
            }
        elif cur is None:
            continue
        elif line.startswith(PAGE_PREFIX):
            digits = re.sub(r"\D", "", line)
            cur["page"] = int(digits) if digits else 0
        elif line.startswith(TITLE_PREFIX):
            cur["title"] = line[len(TITLE_PREFIX):].strip()
        elif line.startswith(TYPE_PREFIX):
            continue                      # [类型] table 只是标记，不进正文
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
            prev["pages"].append(b["page"])
            continue

        new = dict(b)
        new["pages"] = [b["page"]]
        merged.append(new)

    return merged


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

        # 够短 -> 整张作为一块
        if len(whole) <= TABLE_MAX_CHARS:
            pieces = [whole]
        else:
            # 超长 -> 按行拆分，每片都带上原始表头，缺了表头数据就读不懂了。
            #
            # 为什么是"按字符数装桶"而不是"按行数均分"：
            #   按行数均分（旧线路的做法）保证不了每片的长度 ——
            #   表格各行的长度差得很远，均分后照样会出现 4723 字符的超大片
            #   （实测 Table 64 修订历史表就是，远超 2600 的上限）。
            #   改成顺着行往下装，装到"再加这一行就会超限"就封口，
            #   这样每片都贴着上限、又不会超；只有"单独一行本身就超限"时才没办法。
            buckets: list[list[str]] = []
            cur: list[str] = []
            cur_len = len(header)
            for row in body:
                if cur and cur_len + len(row) + 1 > TABLE_MAX_CHARS:
                    buckets.append(cur)
                    cur = []
                    cur_len = len(header)
                cur.append(row)
                cur_len += len(row) + 1
            if cur:
                buckets.append(cur)

            pieces = ["\n".join([header] + b) for b in buckets]
            notes.append(
                f"- 《{title}》（{page_label}）共 {len(body)} 行、{len(whole)} 字符，"
                f"超过上限 {TABLE_MAX_CHARS}，已按字符数切成 {len(pieces)} 片"
                f"（每片都重复带表头）"
            )

        for i, piece in enumerate(pieces, 1):
            part_note = f"（第 {i}/{len(pieces)} 部分）" if len(pieces) > 1 else ""
            content = (
                f"[{doc_name} {page_label} · 表格{part_note}]\n"
                f"表格标题: {title}\n\n"
                f"{piece}"
            )
            chunks.append({
                "content": content,
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
    if re.match(r"^(Table|Figure)\s+\d+", p):
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
    把正文页切成一堆 500 字左右的小块。

    两条关键规则（直接决定检索质量）：
      1. 遇到新的小节标题 -> 立刻收尾当前块。
      2. 每块开头贴上下文前缀：[手册名 第 N 页 · 正文 · 这一节的标题路径]
    """
    chunks: list[dict] = []
    files = sorted(text_dir.glob("page_*.md"))
    h1 = h2 = ""       # 跨页保留的章节上下文

    for f in files:
        meta, body = read_page_file(f)
        page = int(meta.get("page") or 0)

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
            chunks.append({
                "content": content,
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
            if sum(len(x) + 2 for x in buf) >= TEXT_TARGET_CHARS:
                flush(h1, h2)

        flush(h1, h2)

    return chunks


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
        print("         .venv\\Scripts\\python backend\\p0_1_extract_tables.py")
        print("         .venv\\Scripts\\python backend\\p0_2_extract_text.py")
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

    # ---- 合并、编号、排序 ----
    chunks = table_chunks + text_chunks
    chunks.sort(key=lambda c: (c["page_start"], 0 if c["type"] == "table" else 1))
    for i, c in enumerate(chunks, 1):
        c["id"] = f"{stem}_c{i:04d}"

    # ---- 落盘 ----
    jsonl_path = out_dir / "chunks.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as fp:
        for c in chunks:
            fp.write(json.dumps(c, ensure_ascii=False) + "\n")

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
        f"- 合计：**{len(chunks)} 块**",
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
    report.extend(notes if notes else ["（无需跨页合并或拆表）"])
    report += ["", "## 最长的 5 块（确认没有异常巨大）", ""]
    for c in sorted(chunks, key=lambda x: -x["n_chars"])[:5]:
        preview = c["content"][:80].replace("\n", " ")
        report.append(f"- `{c['id']}` {c['n_chars']} 字符 [{c['type']}] {preview}...")

    (out_dir / "_report.md").write_text("\n".join(report), encoding="utf-8")

    print(f"  表格张数（原始）      : {raw_table_count}")
    print(f"  表格张数（跨页合并后）: {len(merged)}")
    print(f"  表格块                : {len(table_chunks)}")
    print(f"  正文块                : {len(text_chunks)}")
    print(f"  合计                  : {len(chunks)} 块")
    if lens:
        print(f"  总字符数              : {total_chars:,}")
        print(f"  单块 最短/平均/最长   : "
              f"{min(lens)} / {int(statistics.mean(lens))} / {max(lens)}")
    print()
    print(f"  已写出: {to_rel(jsonl_path)}")
    print(f"  已写出: {to_rel(out_dir / '_report.md')}")


if __name__ == "__main__":
    main()
