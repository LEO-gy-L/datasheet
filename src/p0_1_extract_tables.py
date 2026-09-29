# -*- coding: utf-8 -*-
"""
P0 第 1 步：提取 + 清洗 + 过滤表格（新线路的唯一表格脚本）
==========================================================

输出统一格式：
    [来源] STM32F103C8_Datasheet.pdf
    [页码] 37
    [标题] Table 6. Voltage characteristics
    [类型] table

    | Symbol | Ratings | Min | Max | Unit |
    | --- | --- | --- | --- | --- |
    | VDD - VSS | ... | -0.3 | 4.0 | V |

────────────────────────────────────────────────────────────────
2026-09-29 修复记录（这次把旧线路的清洗能力全部搬了回来）
────────────────────────────────────────────────────────────────
【修复 1】清洗逻辑丢失（表格质量回退）
    旧版这个脚本只会替换 7 个特殊字符，其余统统不管，
    所以输出里残留 <br> 标签、Col6/Col7 占位列、** 粗体记号、
    粘连单词（VDDAand / VDDpower），这些脏东西一路进了向量库。
    现在把旧线路（src/legacy/p0_1_tables_v3.py）里成熟的清洗函数
    全部搬了进来，按固定顺序执行：
        strip_markup          去掉 <br> / ** / _ / ~~
        normalize_dashes      7 种"假横线"统一成 ASCII 的 -
        normalize_spaces      \\xa0 换普通空格、折叠连续空格
        fix_glued_words       修 VDDAand -> VDDA and
        fix_sign_spacing      "- 0.3" -> "-0.3"、"VDD+ 4.0" -> "VDD + 4.0"

【修复 2】合并单元格错位
    旧版 fill_merged_cells() 直接拿"坐标网格第 ri 行"去对"输出第 ri 行"，
    但 to_markdown() 常在开头多塞行（表格标题行、第二级表头），
    于是整张表的数据错一行 —— 第 37 页 Table 6 的 ΔVDDx 那行整体右移，
    Table 8 的 Unit 列被填成上一格的 150。
    现在补上 best_offset()：把候选偏移挨个试一遍，
    看哪个让"坐标取到的文字"和"输出文字"重合最多，就用哪个。
    另外补上 drop_placeholder_columns()，把 Col2/Col6 这类占位列整列删掉。

【修复 3】路径不锚定项目根 / 误删风险
    - 路径统一用 ROOT = Path(__file__).resolve().parents[1] 拼绝对路径
    - 清空旧输出前加了护栏：只删 page_*.md，且输出目录名必须以 tables_ 开头，
      防止 --out-dir 传错（比如传成 data/tables_v4）把老成果清空
"""

import argparse
import re
from pathlib import Path

try:
    import pymupdf
except ImportError:
    import fitz as pymupdf


# ---------- 项目根目录 ----------
ROOT = Path(__file__).resolve().parents[1]


# ---------- 配置 ----------
TITLE_SEARCH_PT = 60.0       # 在表格上边框上方 60pt 内搜索标题

# 伪表过滤阈值
DRAW_RATIO_MAX = 0.35          # 图形重叠率超过这个值 -> 伪表
PLACEHOLDER_RE = re.compile(r"^Col\d+$")   # PyMuPDF 认不出表头时的占位名
MIN_TRUE_ROWS = 2              # 真表至少要有 2 行数据
MIN_TRUE_COLS = 2              # 真表至少要有 2 列
MIN_TRUE_CELLS = 4             # 真表至少要有 4 个格子
# 表头里 Col1/Col2 这类占位名的比例上限。
# 0.40 这个值是旧线路在 STM32 + ATmega 两份排版完全不同的手册上交叉验证出来的，
# 别随手调大（第一版写成 0.5 时，第 11 页框图里的 `SUPPLY | Col2` 正好 50%、
# 卡在边界上漏了网，一路混进向量库）。
PLACEHOLDER_MAX_RATIO = 0.40
SINGLE_ROW_MAX_COLS = 3        # 单行表只有"又窄"时才算碎片（见下方注释）
FRAGMENT_MIN_ROWS = 5          # "内容过碎"这条只对 5 行以上的表生效

# 【重要教训，来自旧线路踩的坑，别随便改】
#   旧版本写过"只有一行 -> 剔除"，在 STM32 手册上零误杀，
#   换到 ATmega328P 就一下杀掉 72 张寄存器位定义表：
#       | CLKPCE | - | - | - | CLKPS3 | CLKPS2 | CLKPS1 | CLKPS0 |
#   这是 AVR 手册描述 8 位寄存器的标准格式，天然就是"1 行 8 列"，
#   而且是硬件工程师查得最多的内容。宽单行表必须留，窄单行表才是碎片。

CHAR_MAP = {
    "\xa0": " ",
    "\u2013": "-",
    "\u2212": "-",
    "\u2014": "-",
    "\u2022": "-",
    "\ufb01": "fi",
    "\ufb02": "fl",
}


# ==================================================================
# 第一组：字符层面的清洗（从旧线路 p0_1_tables_v3.py 搬回来）
# ==================================================================

# 这些字符长得都像横线，但编码完全不同（键盘上敲的是最后一个）。
# 统一成 ASCII '-' 之后，用户敲的 "-" 才能检索到它们。
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
    """按固定顺序跑一遍所有清洗规则（顺序不能乱）。"""
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
# 第二组：Markdown 表格的解析与拼装
# ==================================================================

def parse_markdown_table(md: str) -> tuple[list[str], list[list[str]]]:
    """把 markdown 表格拆成 (表头, 数据行)。分隔线 |---|---| 会被跳过。"""
    lines = [
        ln for ln in md.splitlines()
        if ln.strip() and not re.fullmatch(r"\|[\s\-:|]+\|", ln.strip())
    ]
    if not lines:
        return [], []
    header = [c.strip() for c in lines[0].strip("|").split("|")]
    rows = [[c.strip() for c in ln.strip("|").split("|")] for ln in lines[1:]]
    return header, rows


def build_markdown_table(header: list[str], rows: list[list[str]]) -> str:
    """重新拼装 markdown 表格（带上 |---|---| 分隔线，这样才是合法的 markdown 表）。"""
    def fmt(cells: list[str]) -> str:
        return "| " + " | ".join(cells) + " |"

    sep = "|" + "|".join([" --- " for _ in header]) + "|"
    lines = [fmt(header), sep]
    for r in rows:
        # 确保列数一致：少了补空、多了截断
        r = list(r)
        if len(r) < len(header):
            r += [""] * (len(header) - len(r))
        else:
            r = r[:len(header)]
        lines.append(fmt(r))
    return "\n".join(lines)


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
# 第三组：表格结构层面的修复（合并单元格 / 占位列 / 标题）
# ==================================================================

def _norm(text: str) -> str:
    """对齐比对用的归一化：只比"有没有这个信息"，不比排版细节。"""
    text = strip_markup(text or "")
    text = normalize_dashes(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", "", text)
    text = text.replace("|", "")
    return text.lower()


def build_cell_texts(page: pymupdf.Page, table) -> tuple[list, list]:
    """
    把这张表每一格的"真实文字"按坐标取出来，供 best_offset() 用。

    取文字时必须限定 y 范围：纵向合并的格子矩形会跨好几行，
    不限定的话会把整列文字都算进这一格。

    返回 (坐标网格, 每格文字)；合并格（没有独立边框）的文字是 None。
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
      第 43 页的功耗表就是典型：它有两级表头，行数差算出来是 2，
      实际应该是 1，结果整张表的数据错了一行。

    做法：把候选偏移挨个试一遍，看哪个能让"坐标取到的文字"和
          "输出里的文字"重合得最多，就选哪个。
          平局时优先用行数差。
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


def fill_merged_cells(table, rows: list[list[str]],
                      offset: int | None = None) -> list[list[str]]:
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

    if offset is None:
        offset = len(rows) - len(rects_grid)
    if offset < 0:
        return rows

    for ri in range(len(rects_grid)):
        ri_text = ri + offset
        if ri_text >= len(rows):
            break
        cells = rects_grid[ri]

        # 本行 y 中心。cells 元素可能是 Rect 也可能是 tuple，下标 [1]/[3] 都兼容
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
    """删掉跨列合并产生的 Col2/Col6 这类占位名列（只看表头，且不能全删）。"""
    if not rows:
        return rows

    header = rows[0]
    drop_idx = {i for i, c in enumerate(header) if PLACEHOLDER_RE.match(c.strip())}

    if not drop_idx or len(drop_idx) == len(header):
        return rows

    return [[c for i, c in enumerate(row) if i not in drop_idx] for row in rows]


def extract_table_title(rows: list[list[str]]) -> tuple[str, list[list[str]]]:
    """
    回退方案：从 to_markdown() 的行里摘标题。

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

    words = [c.strip() for c in first
             if c.strip() and not PLACEHOLDER_RE.match(c.strip())]
    return " ".join(words), rows[1:]


def find_title_by_coords(page: pymupdf.Page, table) -> str:
    """
    用坐标在表格上方找表格标题 —— 这一步非常关键。

    为什么必须靠坐标找：
      只靠 to_markdown() 的话，只能认出"标题恰好被塞进表格里"的那种表
      （表现为 | Col1 | Table 7. Current characteristics | Col3 |）。
      第 37 页的 Table 6 和 Table 8，PyMuPDF 没把标题塞进表格对象里，
      于是标题整个丢了 —— 输出里只剩一个光秃秃的表头，
      你根本看不出它是哪张表，检索 "Table 6" 也检索不到。

    做法：
      1. 取表格上边框往上 60pt 这个带状区域里的所有文字
      2. 按 y 坐标聚成行（y 差在 3pt 以内算同一行）
      3. 找含 "Table 数字" 的行；如果有多行，取离表格最近的那一行
    """
    x0, y0, x1, y1 = table.bbox

    words = [
        w for w in page.get_text("words")
        if (y0 - TITLE_SEARCH_PT) <= w[1] < y0 and (x0 - 20) <= w[0] <= (x1 + 20)
    ]
    if not words:
        return ""

    # 按 y 聚成行：key 用 y 除以 3 取整，容差 3pt
    lines: dict[int, list] = {}
    for w in words:
        lines.setdefault(round(w[1] / 3), []).append(w)

    candidates = []
    for ws in lines.values():
        ws.sort(key=lambda w: w[0])
        text = " ".join(w[4] for w in ws)
        if re.search(r"Table\s*\d+", text):
            candidates.append((max(w[3] for w in ws), text))   # (行的最大y, 文本)

    if not candidates:
        return ""

    # 取 y 最大的（离表格最近的）那一行
    candidates.sort(key=lambda c: c[0])
    return candidates[-1][1].strip()


# ==================================================================
# 第四组：伪表过滤（判定这张"表"是不是图里的标注框）
# ==================================================================

def rect_overlap_ratio(table_bbox: tuple[float, float, float, float],
                       drawings: list[dict]) -> float:
    """计算表格与页面矢量图形的重叠面积比例。"""
    x0, y0, x1, y1 = table_bbox
    area = max((x1 - x0) * (y1 - y0), 1e-9)
    overlap = 0.0
    for d in drawings:
        if d.get("fill") is not None:      # 带填充色的矩形是表格自身底色，不算
            continue
        r = d.get("rect")
        if r is None:
            continue
        ox = max(0.0, min(x1, r.x1) - max(x0, r.x0))
        oy = max(0.0, min(y1, r.y1) - max(y0, r.y0))
        if ox > 0 and oy > 0:
            overlap += min(ox * oy, area)
    return min(overlap / area, 1.0)


def calc_features(table, raw_md: str, clean_md: str, draw_ratio: float) -> dict:
    """
    计算一张表的真假特征。

    【为什么占位名比例必须在"清洗前"的 raw_md 上算】
      清洗里的 drop_placeholder_columns() 会把 Col2/Col6 整列删掉，
      等清洗完再算，这个比例永远是 0 —— 那条规则就废了。
      平均单元格字数则相反，要在清洗后的文本上算（原始文本混着
      <br> / ** 会把长度虚增）。
    """
    raw_header, _ = parse_markdown_table(raw_md)
    _, rows = parse_markdown_table(clean_md)
    grid = [list(r.cells) for r in table.rows]

    all_cells = [c for r in rows for c in r if c]
    placeholder_ratio = (
        sum(1 for c in raw_header if PLACEHOLDER_RE.match(c.strip())) / len(raw_header)
        if raw_header else 0.0
    )
    avg_len = (sum(len(c) for c in all_cells) / len(all_cells)) if all_cells else 0.0

    return {
        "n_rows": len(grid),
        "n_cols": len(grid[0]) if grid else 0,
        # markdown 输出的列数（= 真正能读到的列数）。
        # 为什么要单独算：坐标网格（grid）常比 markdown 多出几列 ——
        # 框图里的标签框在网格上是"2 列"，转成 markdown 却只剩 `| SUPPLY |` 一列。
        # 只按 grid 判列数会让这种伪表漏网（实测第 11 页那张 `| SUPPLY |` 就是这样进来的）。
        "n_md_cols": len(raw_header),
        "n_text_rows": len(rows),
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
    if f["n_cols"] < MIN_TRUE_COLS:
        return False, f"只有 {f['n_cols']} 列（不构成表）"

    # 坐标网格列数够、但 markdown 只输出 1 列 -> 框图里的标签框
    if f["n_md_cols"] < MIN_TRUE_COLS:
        return False, f"表头只有 {f['n_md_cols']} 列（框图标签框）"

    # 单行表只在"又窄"时才是碎片；宽单行列是寄存器位定义表，必须留
    if f["n_rows"] <= 1 and f["n_cols"] <= SINGLE_ROW_MAX_COLS:
        return False, f"单行且窄 {f['n_cols']} 列（不构成表）"

    total_cells = f["n_rows"] * f["n_cols"]
    if total_cells < MIN_TRUE_CELLS:
        return False, f"格子数太少（{total_cells}）"

    # 清理完一个有效单元格都没有 -> 框图里的标签框（只有框、没有数据）
    if f["avg_cell_len"] <= 0.0:
        return False, "清理后没有任何有效单元格（框图标签框）"

    if f["placeholder_ratio"] > PLACEHOLDER_MAX_RATIO:
        return False, f"表头占位名占 {f['placeholder_ratio']:.0%}（表头识别失败）"

    if f["draw_ratio"] > DRAW_RATIO_MAX:
        return False, f"图形重叠率 {f['draw_ratio']:.0%} 过高"

    # 内容过碎只对多行表生效（单行寄存器表的单元格天然就短）
    if f["n_text_rows"] >= FRAGMENT_MIN_ROWS and f["avg_cell_len"] < 3.0:
        return False, f"内容过碎（平均 {f['avg_cell_len']:.1f} 字符）"

    return True, "无标题但结构完整，保留待复核"


# ==================================================================
# 第五组：把一张表变成干净的 Markdown
# ==================================================================

def table_to_markdown(page: pymupdf.Page, table) -> tuple[str | None, str]:
    """
    把 PyMuPDF 表格对象转成干净的 Markdown。返回 (标题, markdown)。

    步骤顺序不能调换：
      对齐列数 -> 算偏移 -> 补合并格 -> 逐格清洗 -> 摘标题 -> 删占位列 -> 再对齐
    """
    raw = table.to_markdown()
    if not raw:
        return None, ""

    # 解析原始行（跳过分隔线），行首行尾的 | 去掉
    rows: list[list[str]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        if re.fullmatch(r"\|[\s\-:|]+\|", line.strip()):
            continue
        rows.append([c for c in line.strip().strip("|").split("|")])

    if not rows:
        return None, ""

    rows = align_columns(rows)

    # 按内容算出"坐标网格"与"输出行"的对齐偏移（多级表头时不能靠行数差）
    grid, texts = build_cell_texts(page, table)
    offset = best_offset(grid, texts, rows)

    rows = fill_merged_cells(table, rows, offset)
    rows = [[clean_cell(c) for c in r] for r in rows]

    title, rows = extract_table_title(rows)
    rows = drop_placeholder_columns(rows)
    rows = align_columns(rows)

    if not rows:
        return None, ""
    if len(rows) == 1:
        # 只剩表头、没有数据行 -> 不是有效表
        return None, ""

    # 坐标法找标题（上面没拿到时用它补）
    if not title:
        title = clean_cell(find_title_by_coords(page, table))

    md = build_markdown_table(rows[0], rows[1:])
    return title, md


def write_table(out_dir: Path, page_no: int, pdf_name: str,
                title: str, md: str) -> None:
    """按统一格式输出单张表格（一页多表时追加到同一个文件）。"""
    content = (
        f"[来源] {pdf_name}\n"
        f"[页码] {page_no}\n"
        f"[标题] {title}\n"
        f"[类型] table\n\n"
        f"{md}\n"
    )
    page_file = out_dir / f"page_{page_no:03d}.md"
    if page_file.exists():
        page_file.write_text(
            page_file.read_text(encoding="utf-8") + "\n" + content,
            encoding="utf-8",
        )
    else:
        page_file.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="从 PDF 提取、清洗并过滤表格")
    parser.add_argument("--pdf", default="datasheets/STM32F103C8_Datasheet.pdf",
                        help="输入 PDF 路径（相对项目根目录）")
    parser.add_argument("--out-dir", default=None,
                        help="输出目录，默认 data/tables_v5/<pdf_stem>/")
    args = parser.parse_args()

    # 路径统一锚定项目根
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
        out_dir = ROOT / "data" / "tables_v5" / stem
    out_dir.mkdir(parents=True, exist_ok=True)

    # 清理旧输出。安全护栏：只删 page_*.md，且路径里必须有一段以 tables_ 开头
    # （旧版是无条件 unlink，万一 --out-dir 传成 data/tables_v4 会把老成果清空）
    stale = sorted(out_dir.glob("page_*.md"))
    if stale:
        if any(p.startswith("tables_") for p in out_dir.parts):
            for f in stale:
                f.unlink()
            print(f"已清理旧输出 {len(stale)} 个 page_*.md")
        else:
            print(f"[警告] 输出路径里没有 tables_ 开头的目录段（{out_dir}），"
                  f"为安全起见不自动清理旧文件，已跳过")

    doc = pymupdf.open(pdf_path)

    kept = 0
    dropped = 0
    dropped_log: list[tuple[int, int, str]] = []   # (page, table_idx, reason)

    for pno in range(len(doc)):
        page = doc[pno]
        drawings = page.get_drawings()

        tables = page.find_tables().tables
        for ti, table in enumerate(tables, start=1):
            raw_md = table.to_markdown()
            title, md = table_to_markdown(page, table)
            draw_ratio = rect_overlap_ratio(table.bbox, drawings)

            if not md:
                dropped += 1
                dropped_log.append((pno + 1, ti, "解析后没有数据行"))
                continue

            f = calc_features(table, raw_md, md, draw_ratio)
            keep, reason = judge(title, f)

            if not keep:
                dropped += 1
                dropped_log.append((pno + 1, ti, reason))
                continue

            display_title = title or f"第 {pno + 1} 页 表 {ti}"
            write_table(out_dir, pno + 1, pdf_name, display_title, md)
            kept += 1

    doc.close()

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
    print(f"  报告：{out_dir / '_filtered_out.md'}")


if __name__ == "__main__":
    main()
