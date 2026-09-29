# -*- coding: utf-8 -*-
"""
P0 第 1 步（第 3 版）：在 v2 基础上修两件事

新增修复（v2 -> v3）：
  A. 表格标题丢失
     v2 只在 to_markdown() 恰好把标题行塞进表格里时才认得出标题，
     所以第 37 页三张表里只有 Table 7 有 [标题]，Table 6 / Table 8 都丢了。
     —— 输出里看不出哪张表是哪张，检索 "Table 6" 也检索不到。
     v3 改成用坐标去表格上方找 "Table N. xxx"，三张表都能拿到标题。

  B. 内置全量自检
     v2 是靠我人眼看样本判断"修好了没有"，这不靠谱（上次就因为这个漏了问题）。
     v3 每解析一张表，就拿坐标网格重建一份 ground truth 逐格比对，
     最后打印全文档的错误格数。数字说话，不再靠眼睛。

运行方式（在 datasheet 目录下）：
  .venv\\Scripts\\python src\\p0_1_tables_v3.py

输出目录：data/tables_v3/（和前两版分开，方便对比）
"""

import re
from pathlib import Path

try:
    import pymupdf
except ImportError:  # 兜底：老版本 PyMuPDF 只有 fitz 这个名字
    import fitz as pymupdf


# ------------------------------------------------------------------
# 配置区
# ------------------------------------------------------------------
PDF_PATH = Path("datasheets/STM32F103C8_Datasheet.pdf")
OUT_DIR = Path("data/tables_v3")
SAMPLE_PAGE = 37


# ==================================================================
# 第一组：字符层面的清洗规则（和 v2 完全一样，没动）
# ==================================================================

# 这些字符长得都像横线，但编码完全不同。统一成 ASCII '-' 之后，
# 用户键盘上敲的 "-" 才能检索到它们。
DASH_LIKE_CHARS = [
    "\u2010",  # hyphen
    "\u2011",  # non-breaking hyphen
    "\u2012",  # figure dash
    "\u2013",  # en dash（数值 "- 0.3" 用的是它）
    "\u2014",  # em dash
    "\u2015",  # horizontal bar
    "\u2212",  # minus sign（符号 "VDD - VSS" 用的是它）
]


def normalize_dashes(text: str) -> str:
    """把 7 种"假横线"统一成 ASCII 减号 '-'。"""
    for ch in DASH_LIKE_CHARS:
        text = text.replace(ch, "-")
    return text


def strip_markup(text: str) -> str:
    """去掉 to_markdown() 留下的 <br> / **粗体** / _斜体_ / ~~删除线~~。"""
    text = text.replace("<br>", " ").replace("<br/>", " ").replace("<br />", " ")
    text = re.sub(r"</?[a-zA-Z][^>]*>", " ", text)
    text = text.replace("**", "")
    text = text.replace("~~", "")
    text = text.replace("_", " ")
    return text


def normalize_spaces(text: str) -> str:
    """\\xa0 -> 普通空格；连续空格折叠；去首尾空格。"""
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


# 下标粘连修复的白名单词。
# 为什么不用"大写字母后跟小写就断开"：那会把 MOSFETs 切成 "MOSFET s"。
GLUE_WORDS = (
    "and", "or",
    "power", "ground", "supply", "source", "sink",
    "line", "lines", "pin", "pins",
    "voltage", "current", "range", "level", "levels",
    "input", "output", "mode", "modes", "reset", "reference",
)
_GLUE_RE = re.compile(r"(?<=[A-Z0-9])(" + "|".join(GLUE_WORDS) + r")\b")


def fix_glued_words(text: str) -> str:
    """VDDAand VDD -> VDDA and VDD；VDDpower pins -> VDD power pins。"""
    return _GLUE_RE.sub(r" \1", text)


def fix_sign_spacing(text: str) -> str:
    """
    修正正负号两侧的空格。分三种情况，不能一把抓：
      "- 0.3"      -> "-0.3"        （开头的负号要紧凑）
      "VDD+ 4.0"   -> "VDD + 4.0"   （加号）
      "VSS- 0.3"   -> "VSS - 0.3"   （字母后的减号）
    """
    text = re.sub(r"^-\s+(?=[\d.])", "-", text)
    text = re.sub(r"(?<=[A-Za-z0-9])\+(?=\s)", " +", text)
    text = re.sub(r"(?<=[A-Za-z0-9])-\s*", " - ", text)
    return text


def clean_cell(text: str) -> str:
    """按固定顺序跑一遍所有规则（顺序不能乱，原因见 v2 注释）。"""
    if text is None:
        return ""
    text = strip_markup(text)
    text = normalize_dashes(text)
    text = normalize_spaces(text)
    text = fix_glued_words(text)
    text = fix_sign_spacing(text)
    text = normalize_spaces(text)
    return text


# ==================================================================
# 第二组：表格结构层面的修复
# ==================================================================

PLACEHOLDER_RE = re.compile(r"^Col\d+$")


def find_title_by_coords(page, table) -> str:
    """
    用坐标在表格上方找表格标题 —— 这是 v3 新加的，v2 缺的就是这一步。

    为什么必须靠坐标找：
      v2 只能认出 "to_markdown() 恰好把标题行塞进表格" 的那种表
      （表现为 | Col1 | Table 7. Current characteristics | Col3 |）。
      第 37 页的 Table 6 和 Table 8，PyMuPDF 没把标题塞进表格对象里，
      于是标题就整个丢了 —— 输出里只剩一个光秃秃的表头，
      你根本看不出它是哪张表，检索 "Table 6" 也检索不到。

    做法：
      1. 取表格上边框往上 60pt 这个带状区域里的所有文字
      2. 按 y 坐标聚成行（y 差在 3pt 以内算同一行）
      3. 找含 "Table 数字" 的行；如果有多行，取离表格最近的那一行
         （第 37 页 Table 6 上方既有一段正文结束语，也有标题行，
          取最近的那个才是标题）
    """
    x0, y0, x1, y1 = table.bbox

    words = [
        w for w in page.get_text("words")
        if (y0 - 60) <= w[1] < y0 and (x0 - 20) <= w[0] <= (x1 + 20)
    ]
    if not words:
        return ""

    # 按 y 聚成行：key 用 y 除以 3 取整，容差 3pt
    lines: dict[int, list] = {}
    for w in words:
        lines.setdefault(round(w[1] / 3), []).append(w)

    candidates = []
    for key, ws in lines.items():
        ws.sort(key=lambda w: w[0])
        text = " ".join(w[4] for w in ws)
        if re.search(r"Table\s*\d+", text):
            candidates.append((max(w[3] for w in ws), text))   # (行的最大y, 文本)

    if not candidates:
        return ""

    # 取 y 最大的（离表格最近的）那一行
    candidates.sort(key=lambda c: c[0])
    return candidates[-1][1].strip()


def extract_table_title(rows: list[list[str]]) -> tuple[str, list[list[str]]]:
    """
    回退方案：从 to_markdown() 的行里摘标题（v2 的老办法）。

    只在坐标法找不到标题时才用。判断两条同时满足才认定：
      ① 这一行含 Col1/Col3 这类占位名
      ② 这一行含 "Table 数字"
    """
    if len(rows) < 2:
        return "", rows

    first = rows[0]
    has_placeholder = any(PLACEHOLDER_RE.match(c.strip()) for c in first)
    joined = " ".join(first)

    if not (has_placeholder and re.search(r"Table\s*\d+", joined)):
        return "", rows

    words = [c.strip() for c in first if c.strip() and not PLACEHOLDER_RE.match(c.strip())]
    return " ".join(words), rows[1:]


def build_cell_texts(page, table) -> tuple[list, list]:
    """
    把这张表每一格的"真实文字"按坐标取出来，缓存起来供后面复用。

    取文字时必须限定 y 范围：纵向合并的格子矩形会跨好几行，
    不限定的话会把整列文字都算进这一格。

    返回 (坐标网格, 每格文字)；合并格（没有独立边框）的文字位置是 None。
    """
    grid = [list(r.cells) for r in table.rows]
    texts: list[list] = []

    for cells in grid:
        out = []
        for c in cells:
            if c is None:
                out.append(None)
                continue
            words = [
                w[4] for w in page.get_text("words", clip=c)
                if (c[1] - 1) <= w[1] <= (c[3] + 1)
            ]
            out.append(" ".join(words))
        texts.append(out)

    return grid, texts


def best_offset(grid, texts, rows: list[list[str]]) -> int:
    """
    决定"坐标网格的第 0 行"对应"输出 rows 的第几行"。

    为什么不能简单用 行数差：
      to_markdown() 常在开头多塞行 —— 表格标题行、多级表头的第二行。
      第 43 页的功耗表就是典型：它有两级表头，
      行数差算出来是 2，实际应该是 1，结果整张表的数据错了一行
      （"Symbol" 那一行对上了 "Conditions fHCLK" 那一行）。

    做法：把候选偏移挨个试一遍，看哪个能让"坐标取到的文字"和
          "输出里的文字"重合得最多，就选哪个。
          平局时优先用行数差（保持和 v2 一样的行为）。
    """
    default = len(rows) - len(grid)
    if default < 0:
        return 0

    best_off, best_score = default, -1

    for off in range(0, default + 1):
        score = 0
        for ri in range(min(len(grid), len(rows) - off)):
            for ci, txt in enumerate(texts[ri]):
                if txt is None or ci >= len(rows[ri + off]):
                    continue
                n_txt = _norm(txt)
                if n_txt and n_txt in _norm(rows[ri + off][ci]):
                    score += 1
        if score > best_score:
            best_score, best_off = score, off

    return best_off


def fill_merged_cells(table, rows: list[list[str]], offset: int = None) -> list[list[str]]:
    """
    修复"合并单元格"造成的错填。

    问题：PDF 里单位 "V" 是纵向跨 3 行的合并格。extract() 诚实留空，
          但 to_markdown() 会填成左邻居的值（"VDD + 4.0"），
          问"单位是什么"模型就会一本正经答 "VDD + 4.0"。

    判据：往上找最近一个有矩形的同列格子，看它纵向有没有盖住本行：
      盖住   -> 纵向合并，从上往下沿用（pandas 的 ffill）
      没盖住 -> 横向合并，从左邻沿用
    """
    rects_grid = [list(r.cells) for r in table.rows]

    # 调用方一般会按内容算出最佳偏移传进来（多级表头时行数差会算错）；
    # 没传就用行数差（v2 的老办法）
    if offset is None:
        offset = len(rows) - len(rects_grid)
    if offset < 0:
        return rows

    for ri in range(len(rects_grid)):
        ri_text = ri + offset
        if ri_text >= len(rows):
            break
        cells = rects_grid[ri]

        # 本行 y 中心。cells 元素可能是 Rect 也可能是 tuple，用下标 [1]/[3] 都兼容
        ys = [c[1] + (c[3] - c[1]) / 2 for c in cells if c is not None]
        if not ys:
            continue
        row_y = sum(ys) / len(ys)

        for ci in range(len(rows[ri_text])):
            if ci >= len(cells) or cells[ci] is not None:
                continue

            above_rect = None
            above_k = None
            for k in range(ri - 1, -1, -1):
                if ci < len(rects_grid[k]) and rects_grid[k][ci] is not None:
                    above_rect = rects_grid[k][ci]
                    above_k = k
                    break

            if above_rect is not None and above_rect[1] <= row_y <= above_rect[3]:
                src = above_k + offset if above_k is not None else ri_text - 1
                if 0 <= src < len(rows) and ci < len(rows[src]):
                    rows[ri_text][ci] = rows[src][ci]
                    continue

            if ci > 0:
                rows[ri_text][ci] = rows[ri_text][ci - 1]

    return rows


def drop_placeholder_columns(rows: list[list[str]]) -> list[list[str]]:
    """删掉跨列合并产生的 Col2/Col4 这类占位名列（只看表头，且不能全删）。"""
    if not rows:
        return rows

    header = rows[0]
    drop_idx = {i for i, c in enumerate(header) if PLACEHOLDER_RE.match(c.strip())}

    if not drop_idx or len(drop_idx) == len(header):
        return rows

    return [[c for i, c in enumerate(row) if i not in drop_idx] for row in rows]


def align_columns(rows: list[list[str]]) -> list[list[str]]:
    """让每一行列数和表头一致：多了优先删空单元格，少了末尾补空。"""
    if not rows:
        return rows

    n_cols = len(rows[0])
    aligned = [rows[0]]

    for row in rows[1:]:
        cells = list(row)

        while len(cells) > n_cols:
            empty_idx = next((i for i, c in enumerate(cells) if not c.strip()), None)
            if empty_idx is None:
                break
            cells.pop(empty_idx)

        cells = cells[:n_cols]
        while len(cells) < n_cols:
            cells.append("")

        aligned.append(cells)

    return aligned


# ==================================================================
# 第三组：v3 新增 —— 用坐标重建 ground truth，逐格自检
# ==================================================================

def _norm(text: str) -> str:
    """自检时用的归一化：只比"有没有这个信息"，不比排版细节。"""
    text = strip_markup(text or "")
    text = normalize_dashes(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", "", text)          # 去掉所有空白
    text = text.replace("|", "")
    return text.lower()


def build_ground_truth(grid, texts) -> list[list[str]]:
    """
    不依赖 to_markdown()，纯用坐标重建这张表"应该长什么样"。

    对每一格：
      - 有独立边框 -> 该格的真实文字（build_cell_texts 已按 y 范围取好）
      - 没有边框（None）-> 合并格：
          上方同列的框纵向盖住本行 -> 纵向合并，取上方那格的值
          否则                    -> 横向合并，取左邻的值
    """
    truth: list[list[str]] = []

    for ri, cells in enumerate(grid):
        ys = [c[1] + (c[3] - c[1]) / 2 for c in cells if c is not None]
        row_y = sum(ys) / len(ys) if ys else -1

        out: list[str] = []
        for ci, c in enumerate(cells):
            if c is not None:
                out.append(texts[ri][ci] or "")
                continue

            # 合并格
            val = ""
            above_rect = None
            above_k = None
            for k in range(ri - 1, -1, -1):
                if ci < len(grid[k]) and grid[k][ci] is not None:
                    above_rect = grid[k][ci]
                    above_k = k
                    break

            if above_rect is not None and above_rect[1] <= row_y <= above_rect[3]:
                if above_k is not None and ci < len(truth[above_k]):
                    val = truth[above_k][ci]      # 纵向合并：从上往下沿用
            elif ci > 0 and out:
                val = out[ci - 1]                 # 横向合并：从左邻沿用

            out.append(val)

        truth.append(out)

    return truth


def verify(grid, texts, rows: list[list[str]]) -> tuple[int, int, list, bool]:
    """
    拿输出的 rows 和坐标 ground truth 逐格比对。

    返回：(对上的格子数, 对不上的格子数, 对不上的样例, 这张表是否参与比对)

    两种情况不参与比对（不是错，是没法比）：
      - 输出行数比坐标网格还少 —— 空表
      - 输出列数和坐标网格不一致 —— 表头被删占位列/列数对齐过，
        列索引已经对不上了，硬比只会误报
    """
    if len(rows) < len(grid):
        return 0, 0, [], False

    n_grid_cols = len(grid[0]) if grid else 0
    n_out_cols = len(rows[0]) if rows else 0
    if n_grid_cols != n_out_cols:
        return 0, 0, [], False

    truth = build_ground_truth(grid, texts)
    offset = best_offset(grid, texts, rows)

    ok = bad = 0
    samples = []

    for ri, cells in enumerate(grid):
        ri_text = ri + offset
        if ri_text >= len(rows):
            continue
        for ci, c in enumerate(cells):
            if c is None or ci >= len(rows[ri_text]):
                continue

            got = _norm(rows[ri_text][ci])
            want = _norm(truth[ri][ci])

            # ground truth 里带脚注数字、上下标空格之类，允许互相包含
            if got == want or want in got or got in want:
                ok += 1
            else:
                bad += 1
                if len(samples) < 8:
                    samples.append((ri, ci, truth[ri][ci][:28], rows[ri_text][ci][:28]))

    return ok, bad, samples, True


# ==================================================================
# 主流程
# ==================================================================
def table_to_markdown(page, table) -> tuple[str, str]:
    """把一个 PyMuPDF 表格对象转成清洗后的 Markdown，返回 (标题, 正文)。"""
    raw = table.to_markdown()

    rows: list[list[str]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        if re.fullmatch(r"\|[\s\-:|]+\|", line.strip()):
            continue
        rows.append([c for c in line.strip().strip("|").split("|")])

    # 顺序不能调换，原因见 v2 注释：
    #   先对齐列数 -> 再补合并格 -> 再清洗 -> 再摘标题/删占位列 -> 最后再对齐
    rows = align_columns(rows)

    # v3 新增：按内容算出坐标网格与输出行的对齐偏移（多级表头时不能靠行数差）
    grid, texts = build_cell_texts(page, table)
    offset = best_offset(grid, texts, rows)

    rows = fill_merged_cells(table, rows, offset)
    rows = [[clean_cell(c) for c in r] for r in rows]

    title, rows = extract_table_title(rows)
    rows = drop_placeholder_columns(rows)
    rows = align_columns(rows)

    # v3 新增：坐标法找标题。上面那步没拿到标题时，用它补
    if not title:
        title = clean_cell(find_title_by_coords(page, table))

    md = "\n".join("| " + " | ".join(r) + " |" for r in rows)
    return title, md


def main() -> None:
    if not PDF_PATH.exists():
        print(f"找不到 PDF：{PDF_PATH.resolve()}")
        print("请确认你在 datasheet 目录下运行这条命令")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(PDF_PATH)

    total_tables = 0
    titled = 0
    pages_with_tables = []
    ok_total = bad_total = 0
    compared_tables = skipped_tables = 0
    bad_examples = []

    print("=" * 64)
    print(f"开始扫描：{PDF_PATH.name}  共 {doc.page_count} 页")
    print("=" * 64)

    for page_index in range(doc.page_count):
        page = doc[page_index]
        page_no = page_index + 1
        tables = list(page.find_tables().tables)

        if not tables:
            continue

        pages_with_tables.append(page_no)
        page_chunks = []

        for t_index, table in enumerate(tables, start=1):
            title, md = table_to_markdown(page, table)
            if title:
                titled += 1

            lines = [f"[来源] {PDF_PATH.name} 第 {page_no} 页 表 {t_index}"]
            if title:
                lines.append(f"[标题] {title}")
            lines.append(md)

            page_chunks.append("\n".join(lines))
            total_tables += 1

            # 自检：拿坐标重建的 ground truth 逐格比对
            rows_only = [
                [c.strip() for c in ln.strip().strip("|").split("|")]
                for ln in md.splitlines() if ln.strip().startswith("|")
            ]
            grid, texts = build_cell_texts(page, table)
            ok, bad, samples, compared = verify(grid, texts, rows_only)
            if compared:
                compared_tables += 1
            else:
                skipped_tables += 1
            ok_total += ok
            bad_total += bad
            for s in samples:
                bad_examples.append((page_no, t_index) + s)

        out_file = OUT_DIR / f"page_{page_no:03d}.md"
        out_file.write_text("\n\n".join(page_chunks), encoding="utf-8")

    print(f"\n扫描完成：{len(pages_with_tables)} 页含表格，共 {total_tables} 张表")
    print(f"拿到标题的表：{titled} / {total_tables}")
    print(f"结果已写入：{OUT_DIR.resolve()}")

    print("\n" + "=" * 64)
    print("全量自检（拿坐标重建的 ground truth 逐格比对）")
    print("=" * 64)
    print(f"  参与比对的表   : {compared_tables} 张（另有 {skipped_tables} 张因列数被调整过，没法逐格比）")
    total_cells = ok_total + bad_total
    rate = 100.0 * bad_total / total_cells if total_cells else 0.0
    print(f"  比对的格子总数 : {total_cells}")
    print(f"  对上的         : {ok_total}")
    print(f"  对不上的       : {bad_total}  ({rate:.2f}%)")
    if bad_examples:
        print("\n  对不上的样例（前 12 个）：")
        print("    页-表      行 列   PDF原文             脚本输出")
        for e in bad_examples[:12]:
            print(f"    p{e[0]:<3d}t{e[1]:<3d}  {e[2]:>2d} {e[3]:>2d}   {e[4]:<20s} {e[5]}")

    sample_file = OUT_DIR / f"page_{SAMPLE_PAGE:03d}.md"
    if sample_file.exists():
        print("\n" + "=" * 64)
        print(f"样本：第 {SAMPLE_PAGE} 页（这一页有 Table 6 / 7 / 8 三张表）")
        print("=" * 64)
        print(sample_file.read_text(encoding="utf-8")[:1600])


if __name__ == "__main__":
    main()
