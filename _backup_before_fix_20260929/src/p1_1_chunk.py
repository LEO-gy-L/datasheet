# -*- coding: utf-8 -*-
"""
P1 第 1 步：把 P0 的产物（表格 md + 正文 md）切成适合检索的小块（chunk）。

为什么必须切块，而不是整页塞进去：
    向量 embedding 会把【一整段文字】压成一串数字（比如 2048 个小数），
    这串数字表达的是"这段文字整体在讲什么"。
    如果一段里又讲电源、又讲引脚、又讲定时器，压出来的数字就什么都不像，
    检索时就匹配不上任何具体问题。
    所以要先把文档剪成"一张卡片只讲一件事"的小块。

本脚本处理三类数据问题（都是实测发现的）：
    1. 一页有多张表     -> 按 [来源] 标记切分成独立的表
    2. 一张表跨了好几页 -> 表 5 (引脚定义) 横跨第 30~33 页，必须拼回来，
                          否则检索"PB10 引脚"只能拿到其中一页的碎片
    3. 个别表太大       -> 超过阈值的表按行拆分，但每片都重复带表头，
                          否则只有列名没有数据、或只有数据没有列名

输出：
    data/chunks/<手册名>/chunks.jsonl     每行一个 JSON，供下一步入库用
    data/chunks/<手册名>/_report.md       人读的统计报告，便于审计

用法：
    python src/p1_1_chunk.py
    python src/p1_1_chunk.py --pdf datasheets/ATmega328P_Datasheet.pdf
"""

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


# ==================================================================
# 可调参数（都集中在这里，方便实验）
# ==================================================================

TEXT_TARGET_CHARS = 500      # 正文块的目标长度（字符）。够讲清一件事，又不至于太杂
TEXT_MAX_CHARS = 900         # 正文块上限，超过就强制切断
TABLE_MAX_CHARS = 2600       # 表格块上限。超过就按行拆分，每片重复带表头

# 表格【去重的 key】用：第 N 页里的第几张表
SOURCE_RE = re.compile(r"第\s*(\d+)\s*页\s*表\s*(\d+)")
TITLE_PREFIX = "[标题]"
SOURCE_PREFIX = "[来源]"

# 小节编号，如 "2.3" / "2.3.1" / "A.1"
SECTION_NUM_RE = re.compile(r"^([0-9]+(?:\.[0-9]+)+|[A-Z]\.\d+)\s+(\S.*)$")

# "Table 5. xxx (continued)" 这类跨页续表标记
CONTINUED_RE = re.compile(r"\(\s*continued\s*\)", re.IGNORECASE)


# ==================================================================
# 通用小工具
# ==================================================================

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


def est_tokens(n_chars: int) -> int:
    """
    粗略估算 token 数。

    为什么除以 3.5：英文技术文档里 1 个 token 平均对应 3~4 个字符
    （英文单词常常整词就是一个 token，比中文省）。
    这里只用来估算费用，不需要精确 —— 真正的计费以 API 返回值为准。
    """
    return max(1, int(n_chars / 3.5))


def split_markdown_table(md: str) -> tuple[list[str], list[str]]:
    """
    把一张 markdown 表格拆成 (表头两行, 数据行)。

    markdown 表格长这样：
        | Symbol | Ratings | Min | Max |        <- 表头
        | --- | --- | --- | --- |               <- 分隔行（缺了就渲染不出表格）
        | VDD | xxx | -0.3 | 4.0 |              <- 数据行
        | VIN | xxx | xxx | 4.0 |
    拆开是为了：拆行时能把表头重复贴到每一片上。
    """
    rows = [ln for ln in md.splitlines() if ln.strip().startswith("|")]
    if len(rows) < 2:
        return [], rows
    header = rows[:2]
    body = rows[2:]
    return header, body


# ==================================================================
# 一、表格切块
# ==================================================================

def parse_table_file(path: Path) -> list[dict]:
    """
    解析一个 page_XXX.md，返回里面所有表的列表。

    一个文件可能含多张表，靠 [来源] 行分隔，例如：
        [来源] STM32F103C8_Datasheet.pdf 第 37 页 表 1
        [标题] Table 6. Voltage characteristics
        | Symbol | ... |
        ...
        [来源] STM32F103C8_Datasheet.pdf 第 37 页 表 2
        [标题] Table 7. Current characteristics
        ...
    """
    blocks: list[dict] = []
    cur: dict | None = None

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()

        if line.startswith(SOURCE_PREFIX):
            m = SOURCE_RE.search(line)
            if cur is not None:
                blocks.append(cur)
            cur = {
                "page": int(m.group(1)) if m else 0,
                "index": int(m.group(2)) if m else 0,
                "title": "",
                "lines": [],
            }
        elif line.startswith(TITLE_PREFIX):
            if cur is not None:
                cur["title"] = line[len(TITLE_PREFIX):].strip()
        elif cur is not None:
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

    合并时去重：续页会重新印一遍表头，要把它删掉，只保留第一页那份。
    """
    merged: list[dict] = []

    for b in blocks:
        key = normalize_title(b["title"])

        # 标题为空 -> 不敢合并（怕把几张互不相干的表粘成一块）
        if key and merged and normalize_title(merged[-1]["title"]) == key:
            prev = merged[-1]
            header, body = split_markdown_table(b["md"])
            prev_body = "\n".join(split_markdown_table(prev["md"])[1])
            prev["md"] = prev_body + ("\n" + "\n".join(body) if body else "")
            prev["pages"].append(b["page"])
            continue

        new = dict(b)
        new["pages"] = [b["page"]]
        merged.append(new)

    return merged


def make_table_chunks(blocks: list[dict], doc_name: str) -> tuple[list[dict], list[str]]:
    """
    把合并后的表变成 chunk。超长的表按行拆，每片重复贴表头。
    """
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

        header, body = split_markdown_table(b["md"])

        if not body:
            continue

        whole = "\n".join(header + body) if header else "\n".join(body)

        # 够短 -> 整张作为一块
        if len(whole) <= TABLE_MAX_CHARS:
            pieces = [whole]
        else:
            # 超长 -> 按行拆分，每片都带上原始表头，缺了表头数据就读不懂了。
            #
            # 为什么是"先算片数、再均分行"，而不是"攒够一片就切"：
            #   后一种在临界处会出事 —— 一张 2919 字符的表按 2600 切，
            #   要到最后一行才触发那一次切分，结果要么等于没拆，
            #   要么拆成 [2600, 319] 这种头重脚轻的两片。
            #   先算出总共需要几片，再把行平均分下去，才能得到均衡的片。
            n_parts = -(-len(whole) // TABLE_MAX_CHARS)      # 向上取整
            per_part = -(-len(body) // n_parts)              # 每片分几行
            pieces = [
                "\n".join(header + body[i:i + per_part])
                for i in range(0, len(body), per_part)
            ]

            notes.append(
                f"- 《{title}》（{page_label}）共 {len(body)} 行、{len(whole)} 字符，"
                f"超过上限 {TABLE_MAX_CHARS}，已【均分】成 {len(pieces)} 片"
                f"（每片约 {len(whole) // len(pieces)} 字符，都带表头）"
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
                "page_start": pages[0],
                "page_end": pages[-1],
                "type": "table",
                "title": title,
                "part": f"{i}/{len(pieces)}",
                "n_chars": len(content),
            })

        if len(pages) > 1:
            notes.append(
                f"- 《{title}》横跨原 {pages} 页，已合并为完整一张"
            )

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
    if SECTION_NUM_RE.match(p):
        return True
    if re.match(r"^(Table|Figure)\s+\d+", p):
        return True
    if p.endswith((".", ",", ";", ":")):
        return False
    return len(p) < 70


def update_headings(p: str, h1: str, h2: str) -> tuple[str, str]:
    """
    维护"我当前读到哪一节了"。

    编号里有几个点就代表几级：
        "6 Electrical characteristics"     -> 一级，更新 h1
        "6.2 Absolute maximum ratings"     -> 二级，更新 h2
        "6.2.1 xxx"                        -> 三级，也当作 h2（更细的上下文）
    """
    m = SECTION_NUM_RE.match(p)
    if not m:
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
         好处：一个块永远只属于同一节，不会把"ADC"和"定时器"混在一起。
      2. 每块开头贴上下文前缀：[手册名 第 N 页 · 正文 · 这一节的标题路径]
         好处：切出来的块本身往往缺主语（比如一堆 "The maximum frequency is 72 MHz"），
               贴上标题后才知道讲的是哪个芯片的什么部分。
    """
    chunks: list[dict] = []
    files = sorted(text_dir.glob("page_*.md"))
    h1 = h2 = ""

    for f in files:
        lines = f.read_text(encoding="utf-8").splitlines()

        page = 0
        body_start = 0
        for i, ln in enumerate(lines[:4]):
            m = SOURCE_RE.search(ln) or re.search(r"第\s*(\d+)\s*页", ln)
            if m:
                page = int(m.group(1))
                body_start = i + 1

        # 去掉 [来源] / [页码] 这些元数据行，只留正文
        body_lines = []
        for ln in lines[body_start:]:
            if ln.startswith(SOURCE_PREFIX) or ln.startswith("[页码]"):
                continue
            body_lines.append(ln)

        paragraphs = [
            p.strip()
            for p in "\n".join(body_lines).split("\n\n")
            if p.strip()
        ]

        buf: list[str] = []
        buf_len = 0

        def flush(cur_h1: str, cur_h2: str) -> None:
            """把攒够的内容打包成一块。"""
            nonlocal buf, buf_len
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
                "page_start": page,
                "page_end": page,
                "type": "text",
                "title": path,
                "part": "1/1",
                "n_chars": len(content),
            })
            buf = []
            buf_len = 0

        for p in paragraphs:
            if is_heading(p):
                # 换节了：先把上一节的收尾，再记录新标题
                flush(h1, h2)
                h1, h2 = update_headings(p, h1, h2)
                continue

            buf.append(p)
            buf_len += len(p) + 2

            if buf_len >= TEXT_TARGET_CHARS:
                flush(h1, h2)

        flush(h1, h2)

    return chunks


# ==================================================================
# 主流程
# ==================================================================

def main() -> None:
    ap = argparse.ArgumentParser(description="切块：把 P0 产物切成检索用的小块")
    ap.add_argument("--pdf", default="datasheets/STM32F103C8_Datasheet.pdf")
    ap.add_argument("--out", default=None, help="输出目录，默认是 data/chunks/<手册名>")
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")

    pdf_path = Path(args.pdf)
    if not pdf_path.is_absolute():
        pdf_path = ROOT / pdf_path
    stem = pdf_path.stem
    doc_name = pdf_path.name

    tables_dir = ROOT / "data" / "tables_v4" / stem
    text_dir = ROOT / "data" / "text_v1" / stem

    if not tables_dir.exists() or not text_dir.exists():
        print(f"[错误] 找不到 P0 的产物目录：{tables_dir} 或 {text_dir}")
        print("       请先运行 src/p0_2_filter_tables.py 和 src/p0_3_text.py")
        sys.exit(1)

    out_dir = Path(args.out) if args.out else ROOT / "data" / "chunks" / stem
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 66)
    print(f"切块：{doc_name}")
    print("=" * 66)

    # ---- 表格 ----
    blocks: list[dict] = []
    for f in sorted(tables_dir.glob("page_*.md")):
        blocks.extend(parse_table_file(f))

    # 按 (页码, 表序号) 排序，保证跨页合并时顺序正确
    blocks.sort(key=lambda b: (b["page"], b["index"]))
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
        f"- 单块长度：最短 {min(lens)}，最长 {max(lens)}，"
        f"平均 {int(statistics.mean(lens))}，中位数 {int(statistics.median(lens))}",
        f"- embedding-3 费用估算：约 ¥{toks / 1_000_000 * 0.5:.4f}",
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

    print(f"  表格张数（原始）    : {raw_table_count}")
    print(f"  表格张数（跨页合并后）: {len(merged)}")
    print(f"  表格块              : {len(table_chunks)}")
    print(f"  正文块              : {len(text_chunks)}")
    print(f"  合计                : {len(chunks)} 块")
    print(f"  总字符数            : {total_chars:,}（约 {toks:,} token）")
    print(f"  单块 最短/平均/最长 : {min(lens)} / {int(statistics.mean(lens))} / {max(lens)}")
    print(f"  预估 embedding 费用 : 约 ¥{toks / 1_000_000 * 0.5:.4f}")
    print()
    print(f"  已写出: {jsonl_path.relative_to(ROOT)}")
    print(f"  已写出: {(out_dir / '_report.md').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
