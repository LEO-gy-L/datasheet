# -*- coding: utf-8 -*-
"""
表格结构重建（按坐标，不依赖 to_markdown）
=========================================

【为什么必须自己重建 —— 实测证据】

CH32F103 手册第 2 页的「表1-1 CH32F103x 产品资源分配」，PyMuPDF 的
`find_tables()` 报的是 **22 行 × 14 列**，但真实只有 **5 列**。
多出来的 9 列全是**双线边框**留下的碎片（宽 5.3pt）：

    列0  85.8→184.1  98.3  行标签列
    列1  184.1→189.4  5.3  ← 碎片
    列2  189.4→261.2  71.8  CH32F103 C6T6
    列3  261.2→266.7  5.5  ← 碎片
    列4  266.7→272.0  5.3  ← 碎片
    ...

后果是 `to_markdown()` 直接报废：

    |产品型号<br>资源差异|Col2|Col3|CH32F103|Col5|Col6|CH32F103|...
    |芯片引脚数|芯片引脚数|48|48|48|48|48|48|48|48|48|64|64|64|

「48」重复 12 次，你根本看不出哪个 48 属于哪个型号。

【更隐蔽的一层：表头和数据的列边界根本不是同一套】

    表头行的列边界：  189.4 | 261.2 | 272.0 | 339.1 | 349.9 | 424.3 ...
    数据行的列边界：  184.1 | 266.7 | 344.6 | 429.8 | 520.9

看出来了吗？表头写的是 189.4→261.2，数据写的是 184.1→266.7。
**同一列，两套坐标**。所以任何"按列号对齐"的做法（包括 PyMuPDF 自己的
`to_markdown()`）都必然错位。唯一的出路是**按 x 坐标的重叠关系**来判断
"这个数据属于哪一列"。

【本模块的做法】

    ① 收集所有单元格的精确坐标
    ② 用"投票法"找出真实的行/列边界
       （真边界的值会被很多单元格共用；碎片边界只被一两个用到）
    ③ 按坐标重叠把每个单元格归位
    ④ 纵向合并的单元格 -> 向下继承（用户明确要求）
       横向合并的单元格 -> 只填最左列（避免标签重复）
    ⑤ 多行表头竖着拼成一列一个标签：CH32F103 + C6T6 -> "CH32F103 C6T6"
    ⑥ 斜线表头的两条信息都保留（用户明确要求"斜线表都全传入"）
    ⑦ 每个数据点序列化成一句自描述文本：
           CH32F103 C6T6 · 芯片引脚数 = 48
       这样"48"再也不会脱离它的型号表头 —— 检索"CH32F103C6T6 的引脚数"
       才能命中。

【不做什么】
    不做 OCR。实测这份手册 29 页可抽取 32512 字符，需要 OCR 的页数 = 0，
    文本层是完整的，问题全在"结构"而不在"认不认得字"。
"""
from __future__ import annotations

from dataclasses import dataclass, field

try:
    import pymupdf
except ImportError:                     # pragma: no cover
    import fitz as pymupdf

from backend.app.ingestion.cn_clean import clean_cell_text, smart_join

# ==================================================================
# 可调参数
# ==================================================================

# 边界聚簇容差（pt）。坐标值相差小于它的，视为同一条边界。
# 为什么需要：PDF 里同一条竖线在不同行可能报 184.1 和 184.15，要当成同一个。
BOUND_TOL = 1.5

# 两条相邻边界近于这个值 -> 判定为"双线边框"，只保留一条。
# 实测双线边框总宽 5.3~5.5pt，所以 8.0 足够把它们并掉，
# 同时不会误合并正常的窄列（实测最窄的真实列是 67pt 宽，差得很远）。
MIN_BOUND_GAP = 8.0

# 一条边界至少要被"这么多比例的行"用到，才算真边界。
# 碎片边界（如 189.4）只出现在表头那一两行，比例极低，会被过滤掉。
MIN_VOTES_RATIO = 0.12
MIN_VOTES_FLOOR = 2        # 绝对下限：小表格也得能跑

# 单元格与某一列的重叠面积要超过"该列宽度 × 这个比例"才算覆盖它。
# 0.4 而不是 0.5：双线边框会让边界差几个 pt，太严会把正常单元格判掉。
COVER_RATIO = 0.4

# 斜线判据：一条线段 dx、dy 都超过这两个值，才认为是斜线（不是表格线）
DIAG_MIN_DX = 10.0
DIAG_MIN_DY = 5.0

# 自描述句的分隔符
REC_SEP = " · "


# ==================================================================
# 数据结构
# ==================================================================

@dataclass
class Cell:
    """一个单元格：精确坐标 + 清洗后的文本。"""
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    is_diagonal: bool = False      # 斜线表头（左上角那格）

    def key(self) -> tuple[float, float, float, float]:
        """去重用：坐标四舍五入到 0.1pt。"""
        return (round(self.x0, 1), round(self.y0, 1),
                round(self.x1, 1), round(self.y1, 1))

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass
class RebuiltTable:
    """重建结果。"""
    col_headers: list[str]           # 每列的列头（多行表头已竖拼）
    grid: list[list[str]]            # 完整网格（含表头行，已填充跨行/跨列）
    header_rows: int                 # 表头占了前几行
    label_cols: int                  # 前几列是"行标签列"
    data_col_start: int              # 数据从第几列开始
    diagonal: bool = False           # 是否含斜线表头
    markdown: str = ""               # 给人/模型看的 markdown
    records: list[str] = field(default_factory=list)   # 自描述句列表

    @property
    def n_data_cols(self) -> int:
        return len(self.col_headers) - self.data_col_start

    @property
    def n_data_rows(self) -> int:
        return len(self.grid) - self.header_rows


# ==================================================================
# 一、收集单元格
# ==================================================================

def _text_of(page: "pymupdf.Page", rect: "pymupdf.Rect") -> str:
    """
    取一个矩形区域里的文字。

    用 get_textbox 而不是 get_text("words")：
      get_textbox 会按阅读顺序把区域内的文字拼好，正是单元格需要的。
    """
    try:
        raw = page.get_textbox(rect)
    except Exception:
        return ""
    return clean_cell_text(raw or "")


def find_diagonals(page: "pymupdf.Page",
                   bbox: tuple[float, float, float, float]
                   ) -> list["pymupdf.Rect"]:
    """
    找出表格区域内的**斜线**（斜线表头那条对角线）。

    判据：一条线段，dx 大、dy 也大 —— 表格线一定是水平或垂直的，
    所以"又横又竖"的线只可能是斜线表头画的对角线。

    实测第 2 页左上角：线段 (85.8,344.5)->(184.0,380.8)，dx=98.2 dy=36.4。
    """
    x0, y0, x1, y1 = bbox
    box = pymupdf.Rect(x0 - 2, y0 - 2, x1 + 2, y1 + 2)

    out: list[pymupdf.Rect] = []
    try:
        drawings = page.get_drawings()
    except Exception:
        return out

    for d in drawings:
        r = d.get("rect")
        if r is None or not box.intersects(r):
            continue
        for item in d.get("items", []):
            if item[0] != "l":
                continue
            p1, p2 = item[1], item[2]
            dx = abs(p2.x - p1.x)
            dy = abs(p2.y - p1.y)
            if dx >= DIAG_MIN_DX and dy >= DIAG_MIN_DY:
                out.append(pymupdf.Rect(
                    min(p1.x, p2.x), min(p1.y, p2.y),
                    max(p1.x, p2.x), max(p1.y, p2.y),
                ))
    return out


def extract_cells(page: "pymupdf.Page", table) -> tuple[list[Cell], bool]:
    """
    从 PyMuPDF 的 Table 对象里取出所有单元格（带精确坐标 + 文本）。

    必须去重：table.rows 里同一个物理单元格会在多行里重复出现
    （纵向合并的格子尤其明显 —— "定时器"会出现在它跨越的每一行里）。

    返回 (单元格列表, 是否含斜线表头)。
    """
    diags = find_diagonals(page, tuple(table.bbox))

    cells: list[Cell] = []
    seen: set[tuple[float, float, float, float]] = set()

    for row in table.rows:
        for c in row.cells:
            if c is None:
                continue
            rect = pymupdf.Rect(c)
            cell = Cell(rect.x0, rect.y0, rect.x1, rect.y1, "")

            k = cell.key()
            if k in seen:
                continue
            seen.add(k)

            cell.text = _text_of(page, rect)
            # 斜线判定：这个格子的范围与某条斜线显著重叠
            for d in diags:
                inter = pymupdf.Rect(
                    max(cell.x0, d.x0), max(cell.y0, d.y0),
                    min(cell.x1, d.x1), min(cell.y1, d.y1),
                )
                if inter.width > 0 and inter.height > 0:
                    cell.is_diagonal = True
                    break

            cells.append(cell)

    has_diag = any(c.is_diagonal for c in cells)
    return cells, has_diag


# ==================================================================
# 二、投票法找真实边界
# ==================================================================

def detect_bounds(cells: list[Cell], axis: int, n_rows_hint: int) -> list[float]:
    """
    用"投票法"找出真实的行边界或列边界。

    axis=0 -> 找列边界（用 x0 / x1）
    axis=1 -> 找行边界（用 y0 / y1）

    原理（实测验证过，很稳）：
        真边界会被**很多**单元格共用 —— 因为它左边格子的右边界、
        右边格子的左边界，都是同一个值，每行都投一票。
        碎片边界只被一两个格子用到，票数极低。

    实测第 2 页的列坐标投票结果：
        184.1 -> 10 票（真边界）      189.4 -> 2 票（碎片）
        266.7 -> 10 票（真边界）      261.2 -> 2 票（碎片）
        344.6 -> 10 票（真边界）      349.9 -> 1 票（碎片）

    三道筛选：
        ① 聚簇：相差 < BOUND_TOL 的坐标算同一条边界
        ② 票数闸门：票数 >= max(2, 行数 × 0.12)
        ③ 间距闸门：两条边界近于 MIN_BOUND_GAP 时，只留票多的那条
           （专门对付双线边框 —— 它们离得近，票又少）
    """
    from collections import Counter

    start_i = axis
    end_i = axis + 2

    votes: Counter[float] = Counter()
    for c in cells:
        coords = (c.x0, c.y0, c.x1, c.y1)
        votes[round(coords[start_i], 1)] += 1
        votes[round(coords[end_i], 1)] += 1

    if not votes:
        return []

    # ---- ① 聚簇 ----
    values = sorted(votes)
    clusters: list[list[tuple[float, int]]] = []
    for v in values:
        if clusters and v - clusters[-1][-1][0] <= BOUND_TOL:
            clusters[-1].append((v, votes[v]))
        else:
            clusters.append([(v, votes[v])])

    # 每簇取"票数最多的那个值"代表这条边界；票数取簇内总和
    bounds: list[tuple[float, int]] = []
    for cl in clusters:
        best_v, _ = max(cl, key=lambda x: (x[1], -x[0]))
        total_votes = sum(v for _, v in cl)
        bounds.append((best_v, total_votes))

    # ---- ② 票数闸门 ----
    threshold = max(MIN_VOTES_FLOOR, int(n_rows_hint * MIN_VOTES_RATIO))
    bounds = [(v, n) for v, n in bounds if n >= threshold]
    if len(bounds) < 2:
        # 兜底：闸门太严时退回票数最高的若干个（保住至少 2 条边界）
        bounds = sorted(
            [(v, n) for v, n in
             ((max(cl, key=lambda x: x[1])[0],
               sum(x[1] for x in cl)) for cl in clusters)],
            key=lambda x: x[0],
        )[:2]

    # ---- ③ 间距闸门：双线边框只留一条 ----
    kept: list[tuple[float, int]] = []
    for v, n in bounds:
        if kept and v - kept[-1][0] < MIN_BOUND_GAP:
            # 与上一条太近 -> 留票多的
            if n > kept[-1][1]:
                kept[-1] = (v, n)
            continue
        kept.append((v, n))

    return [v for v, _ in kept]


def covered_indices(bounds: list[float], a: float, b: float) -> list[int]:
    """
    一个单元格的 [a, b] 区间，覆盖了 bounds 划出的哪几段（列或行）。

    判据：重叠长度 > 该段宽度的 COVER_RATIO。
    为什么不要求"完全包含"：双线边框会让表头和数据用两套边界
    （表头 189.4-261.2，数据 184.1-266.7），只有看重叠才认得出来是同一列。
    """
    out: list[int] = []
    for i in range(len(bounds) - 1):
        lo, hi = bounds[i], bounds[i + 1]
        span = hi - lo
        if span <= 0:
            continue
        overlap = min(b, hi) - max(a, lo)
        if overlap > span * COVER_RATIO:
            out.append(i)
    return out


# ==================================================================
# 三、重建网格
# ==================================================================

def build_grid(cells: list[Cell], xb: list[float], yb: list[float]
               ) -> tuple[list[list[str]], list[Cell], dict[tuple[int, int], str]]:
    """
    按坐标把单元格填进网格。

    填充规则（两条，都是有原因的）：

      横跨多列 -> **只填最左那一列**
          为什么：斜线表头/跨列表头会横跨好几列，如果每列都填一遍，
          行标签就会变成"芯片引脚数 / 芯片引脚数"这种重复。
          只填最左列之后：
              跨列格 "芯片引脚数" -> 列0 有值、列1 空  -> 行标签 = "芯片引脚数"
              分列格 "定时器"(列0) + "通用"(列1)        -> 行标签 = "定时器 / 通用"

      纵跨多行 -> **每一行都填**（纵向继承）
          这是用户明确要求的。实测第 2 页"定时器"格跨越 4 行，
          不继承的话下面 3 行就只剩"高级/看门狗/系统时间"，
          丢掉"这些都属于定时器"这层信息。

    同时额外返回一个 wide 映射 {(行, 列): 文本}，记录"这一格被哪个跨列单元格罩着"。
    为什么需要它：
        第 2 页的 "Max：72MHz"（CPU 主频）是一个横跨全部 4 个型号列的单元格，
        按"只填最左"的规则它只落在 C6T6 列，于是数据点只剩
            CH32F103 C6T6 · CPU 主频 = Max：72MHz
        丢了"这一条对 C8T6/C8U6/R8T6 同样成立"的信息。
        有了 wide 映射，序列化时就能对每个被罩住的列都生成一条数据点。

    返回 (网格, 按阅读顺序排好的单元格列表, wide 映射)。
    """
    n_rows = len(yb) - 1
    n_cols = len(xb) - 1
    grid: list[list[str]] = [["" for _ in range(n_cols)] for _ in range(n_rows)]
    wide: dict[tuple[int, int], str] = {}

    # 按阅读顺序（从上到下、从左到右）处理
    ordered = sorted(cells, key=lambda c: (round(c.y0, 1), round(c.x0, 1)))

    for c in ordered:
        if not c.text:
            continue
        cols = covered_indices(xb, c.x0, c.x1)
        rows = covered_indices(yb, c.y0, c.y1)
        if not cols or not rows:
            continue

        # 纵向继承：跨的行全都填
        for r in rows:
            grid[r][cols[0]] = c.text
            # 记录覆盖关系（单列时也记，读回来行为一致）
            for cc in cols:
                wide[(r, cc)] = c.text

    return grid, ordered, wide


# ==================================================================
# 四、表头 / 行标签的判定
# ==================================================================

def count_header_rows(grid: list[list[str]], cells: list[Cell],
                      xb: list[float], yb: list[float]) -> int:
    """
    判断表头占了前几行。

    规则：第 0 行永远是表头；之后**只要这一行没有"独立的行标签单元格"**，
    就还算表头。

    ⚠️ 这里必须用**原始单元格**判断，不能用填充后的 grid —— 这一点踩过坑：
       斜线表头的格子 y 跨度是 344.3→380.7，**横跨了前两行**。
       纵向继承规则会把它同时填进 grid[0][0] 和 grid[1][0]。
       如果拿 grid 判断，grid[1][0] 有值 -> 误判成"数据行"，
       表头行数算成 1，于是第二行表头（C6T6 / C8T6 / C8U6 / R8T6）
       被当成数据行，列头就只剩 "CH32F103"，四个型号全糊在一起。

       改成看"原始单元格里有没有 y0 落在本行、且覆盖第 0 列的格子"：
           行1（362.2~380.7）：只有 C6T6 这种落在第 2 列的格子 -> 没有行标签 -> 仍是表头
           行2（380.7~398.4）：有"芯片引脚数"落在第 0 列        -> 数据开始
        这样才算对。

    实测第 2 页 => header_rows = 2  ✅
    """
    if not grid:
        return 1

    n = 1
    for r in range(1, len(yb) - 1):
        y_lo, y_hi = yb[r], yb[r + 1]
        has_label = False
        for c in cells:
            if not c.text:
                continue
            # y0 落在本行区间内（右边留 BOUND_TOL 的余量，
            # 免得把下一行的起始格子算到本行来）
            if not (y_lo - BOUND_TOL <= c.y0 < y_hi - BOUND_TOL):
                continue
            cols = covered_indices(xb, c.x0, c.x1)
            if cols and cols[0] == 0:
                has_label = True
                break
        if has_label:
            break
        n += 1

    return min(n, len(grid))


def find_label_cols(cells: list[Cell], xb: list[float], header_rows: int,
                    yb: list[float]) -> int:
    """
    判断"行标签列"有几列（即数据从第几列开始）。

    优先看**斜线表头**：斜线格的横跨范围就是行标签列的范围。
    实测第 2 页斜线格 x 从 85.8 到 184.1，正好覆盖列0 + 列1
    （列0 = 85.8→107.4 放"定时器"，列1 = 107.4→184.1 放"通用"）。

    拿不到斜线时退回一个通用判据：
        看表头区里有没有横跨多列的单元格 —— 有的话，
        它覆盖的列就是行标签列（这是"左上角大表头"的通用形态）。
    再拿不到就默认 1 列。
    """
    header_y_end = yb[min(header_rows, len(yb) - 1)]

    # ---- 优先：斜线表头 ----
    for c in cells:
        if c.is_diagonal:
            cols = covered_indices(xb, c.x0, c.x1)
            if cols:
                return max(cols) + 1

    # ---- 次选：表头区里横跨多列的格子 ----
    for c in cells:
        if c.y1 > header_y_end + BOUND_TOL or not c.text:
            continue
        cols = covered_indices(xb, c.x0, c.x1)
        if len(cols) > 1:
            return max(cols) + 1

    return 1


def build_col_headers(col_headers_raw: list[list[str]], label_cols: int,
                      diag_text: str) -> list[str]:
    """
    把多行表头竖着拼成"一列一个标签"。

    实测第 2 页（列2）：
        行0 的 "CH32F103" + 行1 的 "C6T6"  ->  "CH32F103 C6T6"

    拼接用 smart_join：英文之间加空格（CH32F103 + C6T6），
    中文之间不加（"引脚" + "定义" -> "引脚定义"）。
    """
    out: list[str] = []
    for ci, parts in enumerate(col_headers_raw):
        # 行标签列的列头：斜线表头的那两行文字整体放进来
        # （用户要求"斜线表都全传入"—— "产品型号" 和 "资源差异" 一个都不能丢）
        if ci < label_cols and diag_text:
            out.append(diag_text)
            continue

        merged = ""
        seen: set[str] = set()
        for p in parts:
            p = p.strip()
            if not p or p in seen:
                continue          # 去掉跨列复制造成的重复
            seen.add(p)
            merged = smart_join(merged, p) if merged else p
        out.append(merged)
    return out


# ==================================================================
# 五、序列化：每个数据点都带行头 + 列头
# ==================================================================

def make_records(grid: list[list[str]], header_rows: int, label_cols: int,
                 col_headers: list[str],
                 wide: dict[tuple[int, int], str] | None = None
                 ) -> tuple[list[list[str]], list[str]]:
    """
    生成两样东西：
        row_labels  每一行的行标签（可能是多个，如 ["定时器", "通用"]）
        records     自描述句，每个数据点一句

    这就是用户要的核心效果：

        CH32F103 C6T6 · 芯片引脚数 = 48
        CH32F103 C8T6 · 芯片引脚数 = 48
        CH32F103 R8T6 · 芯片引脚数 = 64
        CH32F103 C6T6 · 定时器 / 通用 = 2

    为什么这个格式能救上下文：
        原来的 markdown 是 `|芯片引脚数|48|48|48|48|48|48|...|64|64|`,
        48 完全脱离型号；现在每个 48 都绑定了自己的型号表头，
        检索"CH32F103C6T6 的引脚数是多少"才能命中正确的块。

    wide 参数（可选）：
        记录"哪一格被跨列单元格罩着"。命中的格子即使自己那列是空的，
        也用它来补值 —— 对应第 2 页 "Max：72MHz" 横跨全部 4 个型号列的情况，
        它只落在最左列，但语义上对 4 个型号都成立。
    """
    row_labels: list[list[str]] = []
    records: list[str] = []

    for r in range(header_rows, len(grid)):
        row = grid[r]

        # 行标签：行标签列里所有非空值
        labels = [row[c].strip() for c in range(min(label_cols, len(row)))]
        labels = [x for x in labels if x]
        row_labels.append(labels)

        label_text = " / ".join(labels)

        # 每个数据列一个数据点
        for c in range(label_cols, len(row)):
            value = row[c].strip()
            if not value and wide is not None:
                # 本列为空 -> 看看是不是被某个跨列单元格罩着
                value = wide.get((r, c), "").strip()
            if not value:
                continue
            col_head = col_headers[c] if c < len(col_headers) else ""
            parts = [p for p in (col_head, label_text) if p]
            if not parts:
                continue
            records.append(REC_SEP.join(parts) + f" = {value}")

    return row_labels, records


def render_markdown(col_headers: list[str], grid: list[list[str]],
                    header_rows: int, label_cols: int,
                    row_labels: list[list[str]]) -> str:
    """
    生成 markdown 表格（给人看、也给模型看全貌）。

    行标签列会**合并成一列**（"定时器" + "通用" -> "定时器 / 通用"），
    这样表头和数据列的列数就对得上了，不会再出现"48 重复 12 次"。
    """
    data_cols = list(range(label_cols, len(col_headers)))
    if not data_cols:
        return ""

    # 第一列表头：行标签组的表头
    label_head = col_headers[0] if col_headers else ""
    head_cells = [label_head] + [col_headers[c] for c in data_cols]

    lines = [
        "| " + " | ".join(head_cells) + " |",
        "| " + " | ".join(["---"] * len(head_cells)) + " |",
    ]

    for i, r in enumerate(range(header_rows, len(grid))):
        labels = row_labels[i] if i < len(row_labels) else []
        row = grid[r]
        cells = [" / ".join(labels)]
        for c in data_cols:
            cells.append(row[c].strip() if c < len(row) else "")
        lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(lines)


# ==================================================================
# 六、对外入口
# ==================================================================

def rebuild(page: "pymupdf.Page", table) -> RebuiltTable | None:
    """
    把一张 PyMuPDF 表格重建成结构化结果。

    返回 None 表示这张表重建失败（坐标太乱），调用方应退回旧逻辑。
    宁可退回，也不要输出一张错位的表 —— 错位表格比没有表格更危险，
    因为它会一本正经地给出错误数据。
    """
    cells, has_diag = extract_cells(page, table)
    if len(cells) < 2:
        return None

    n_rows_hint = max(table.row_count, 1)

    xb = detect_bounds(cells, 0, n_rows_hint)
    yb = detect_bounds(cells, 1, n_rows_hint)

    # 列至少 2 条边界（1 列），行至少 2 条边界（1 行）才有意义
    if len(xb) < 2 or len(yb) < 2:
        return None

    grid, _ordered, wide = build_grid(cells, xb, yb)
    if not grid or not grid[0]:
        return None

    header_rows = count_header_rows(grid, cells, xb, yb)
    label_cols = find_label_cols(cells, xb, header_rows, yb)

    # 至少要留一列数据列，否则这不是表
    if label_cols >= len(xb) - 1:
        return None

    # ---- 表头：按列竖拼 ----
    header_y_end = yb[min(header_rows, len(yb) - 1)]
    diag_text = ""
    for c in cells:
        if c.is_diagonal and c.text:
            diag_text = c.text          # 已经是 "产品型号 / 资源差异" 形式
            break

    n_cols = len(xb) - 1
    raw_headers: list[list[str]] = [[] for _ in range(n_cols)]
    for c in sorted(cells, key=lambda c: (round(c.y0, 1), round(c.x0, 1))):
        # 只用表头区的原始单元格（不用填充后的网格 —— 那会带进重复值）
        if c.y0 >= header_y_end - BOUND_TOL or not c.text:
            continue
        for ci in covered_indices(xb, c.x0, c.x1):
            raw_headers[ci].append(c.text)

    col_headers = build_col_headers(raw_headers, label_cols, diag_text)

    # ---- 保证有数据行 ----
    if header_rows >= len(grid):
        return None

    row_labels, records = make_records(grid, header_rows, label_cols,
                                       col_headers, wide)
    if not records:
        return None

    md = render_markdown(col_headers, grid, header_rows, label_cols, row_labels)

    return RebuiltTable(
        col_headers=col_headers,
        grid=grid,
        header_rows=header_rows,
        label_cols=label_cols,
        data_col_start=label_cols,
        diagonal=has_diag,
        markdown=md,
        records=records,
    )


# ==================================================================
# 自测（在项目根目录跑：python -m backend.app.ingestion.table_struct）
# ==================================================================

def _self_test() -> None:
    """拿真实的 CH32F103 第 2 页跑一遍，逐项检查。"""
    from pathlib import Path

    from backend.app.config import ROOT

    pdf = ROOT / "datasheets" / "CH32F103_Datasheet_CN.pdf"
    if not pdf.exists():
        print(f"[跳过] 找不到 {pdf}")
        return

    doc = pymupdf.open(pdf)
    page = doc[1]
    tabs = page.find_tables()
    print("=" * 74)
    print("table_struct 自测 —— CH32F103 第 2 页 表1-1")
    print("=" * 74)
    print(f"  PyMuPDF 原始报数：{tabs.tables[0].row_count} 行 × {tabs.tables[0].col_count} 列")

    t = rebuild(page, tabs.tables[0])
    if t is None:
        print("  ❌ 重建失败")
        doc.close()
        return

    print(f"  重建后：{t.n_data_rows} 数据行 × {t.n_data_cols} 数据列"
          f"（表头 {t.header_rows} 行，行标签 {t.label_cols} 列，斜线表头={t.diagonal}）")
    print()
    print("  列头：")
    for i, h in enumerate(t.col_headers):
        tag = "  [行标签列]" if i < t.label_cols else ""
        print(f"    [{i}] {h!r}{tag}")
    print()
    print("  重建出的 markdown：")
    for ln in t.markdown.splitlines():
        print("    " + ln)
    print()
    print(f"  自描述句（共 {len(t.records)} 条，展示前 14 条）：")
    for rec in t.records[:14]:
        print(f"    {rec}")

    # ---- 断言关键项 ----
    print()
    print("  关键检查：")
    checks: list[tuple[str, bool]] = []
    md = t.markdown
    checks.append(("数据列是 4 列（不是原始的 14 列）", t.n_data_cols == 4))
    checks.append(("表头识别为 2 行", t.header_rows == 2))
    checks.append(("行标签列识别为 2 列", t.label_cols == 2))
    checks.append(("含斜线表头两行文字", "产品型号" in md and "资源差异" in md))
    checks.append(("C6T6 列头拼对", any("C6T6" in h for h in t.col_headers)))
    checks.append(("C8U6 / R8T6 列头都在",
                   any("C8U6" in h for h in t.col_headers)
                   and any("R8T6" in h for h in t.col_headers)))
    checks.append(("引脚数 48 带 C6T6 前缀",
                   "CH32F103 C6T6 · 芯片引脚数 = 48" in t.records))
    checks.append(("引脚数 64 带 R8T6 前缀",
                   "CH32F103 R8T6 · 芯片引脚数 = 64" in t.records))
    checks.append(("闪存 32K 带 C6T6 前缀",
                   "CH32F103 C6T6 · 闪存（字节） = 32K" in t.records))
    checks.append(("竖排「定时器」合并成词（没被拆成 定/时/器）",
                   any("· 定时器 / 通用 = 2" in r for r in t.records)))
    checks.append(("竖排「通信接口」合并成词",
                   any("通信接口 / SPI" in r for r in t.records)))
    checks.append(("斜线表头文字没有多余空格",
                   "产品型号  / " not in md))
    checks.append(("markdown 里不再有重复 48 堆叠",
                   "48|48|48|48|48|48" not in md.replace(" ", "")))

    ok = 0
    for desc, good in checks:
        print(f"    {'✅' if good else '❌'} {desc}")
        ok += 1 if good else 0
    print(f"\n  通过 {ok}/{len(checks)}")

    doc.close()
    print("=" * 74)


if __name__ == "__main__":
    _self_test()
