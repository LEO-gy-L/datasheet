# -*- coding: utf-8 -*-
"""把 PDF 里的矢量框图还原成「大模型读得懂的结构化文本」。

为什么要这个模块
----------------
电子原生的 PDF 里，架构框图**不是一张位图**，而是：
    - 若干矩形图元（每个模块一个框）
    - 若干直线/曲线图元（模块之间的连线）
    - 每个矩形内部压着几个文字列（模块名）

这三样东西的坐标在 PDF 里是写死的，可以直接读出来。
所以「让模型看懂图」这件事，正确做法是**读坐标**，不是把页面渲染成像素再让模型猜。

一个前提判断（很重要）
----------------------
本模块只对**矢量框图**有效。判断方法：
    page.get_text().strip() 有内容  -> 文本层在，PDF 是电子原生的
    len(page.get_images(full=True)) 很大且没文字 -> 扫描件，那才需要 OCR

用法
----
    python backend/figure_extract.py --pdf datasheets/CH32F103_Datasheet_CN.pdf --page 3
    python backend/figure_extract.py --pdf datasheets/CH32F103_Datasheet_CN.pdf --scan
"""

from __future__ import annotations

import argparse
import base64
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf  # PyMuPDF：负责读 PDF 的矢量图元和文字坐标


# ── 可调阈值 ────────────────────────────────────────────────────────────
# 低于这两个尺寸的矩形是「分隔线」而不是「模块框」，要滤掉。
# 这两个值是看图 1-1 的实际比例定的：真正的模块框最小也有 30x12。
MIN_BOX_WIDTH = 15.0
MIN_BOX_HEIGHT = 8.0

# 判定「子框落在父框内部」时允许的误差（PDF 坐标有浮点误差）
CONTAIN_TOLERANCE = 1.0

# 同一行文字的纵向容差：两个字块 y 差小于这个值就算同一行
SAME_LINE_TOLERANCE = 4.0

# 图注的识别：中文写「图1-1 系统框图」，英文写「Figure 1. System block diagram」
CAPTION_RE = re.compile(r"(图\s*\d+[-.]\d+|Figure\s+\d+[-.]?\d*|Fig\.\s*\d+)\s*(.{0,40})")


@dataclass
class FigureBox:
    """一个从矢量图元里还原出来的模块框。"""

    x0: float
    y0: float
    x1: float
    y1: float
    label: str = ""                      # 框内文字，模块名
    children: list[FigureBox] = field(default_factory=list)

    @property
    def rect(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)

    @property
    def area(self) -> float:
        return (self.x1 - self.x0) * (self.y1 - self.y0)


def get_module_boxes(page: pymupdf.Page) -> list[FigureBox]:
    """从一页里取出所有「模块框」。

    步骤：读矢量图元 -> 只留矩形 -> 去重 -> 滤掉细长线条。
    """
    raw_rects: list[tuple[float, float, float, float]] = []

    for drawing in page.get_drawings():
        # drawing["items"] 是这个图元内部的子路径列表，
        # 每个子路径形如 ("re", rect) / ("l", p1, p2) / ("c", ...) 
        # 只看第一个元素（类型码）就够了
        kinds = [item[0] for item in drawing["items"]]
        if "re" in kinds or "qu" in kinds:
            raw_rects.append(tuple(drawing["rect"]))

    # 去重：同一矩形常被描边两次（外框 + 填充），坐标完全一样
    unique: list[tuple[float, float, float, float]] = []
    for rect in raw_rects:
        key = (round(rect[0], 1), round(rect[1], 1), round(rect[2], 1), round(rect[3], 1))
        if key not in [(round(r[0], 1), round(r[1], 1), round(r[2], 1), round(r[3], 1))
                       for r in unique]:
            unique.append(rect)

    boxes: list[FigureBox] = []
    for x0, y0, x1, y1 in unique:
        w, h = x1 - x0, y1 - y0
        if w >= MIN_BOX_WIDTH and h >= MIN_BOX_HEIGHT:
            boxes.append(FigureBox(x0=x0, y0=y0, x1=x1, y1=y1))

    return boxes


def _text_in_box(page: pymupdf.Page, box: FigureBox,
                 exclude: list[FigureBox] | None = None,
                 pad: float = 2.0) -> str:
    """把一个框内部的文字提取出来，按行拼起来。

    get_text("words") 返回的是带坐标的词组：
        (x0, y0, x1, y1, word, block_no, line_no, word_no)
    这也是为什么它比 get_text() 强：能知道每个词在页面上的确切位置。

    exclude 参数是关键：父框必须排除掉被子框盖住的那些字。
    否则「ARM Cortex-M3」这个框的标签会变成
    "ARM Cortex-M3 TPIU NVIC SWD" —— 把里面三个子模块的名字也算进去了。
    """
    words = page.get_text("words")
    exclude = exclude or []

    def swallowed(w) -> bool:
        cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
        return any(e.x0 <= cx <= e.x1 and e.y0 <= cy <= e.y1 for e in exclude)

    inside = [
        w for w in words
        if w[0] >= box.x0 - pad and w[2] <= box.x1 + pad
        and w[1] >= box.y0 - pad and w[3] <= box.y1 + pad
        and not swallowed(w)
    ]
    # 先按行（y 取整避免亚像素抖动），再按行内 x 排序
    inside.sort(key=lambda w: (round(w[1] / SAME_LINE_TOLERANCE), w[0]))

    lines: list[list[str]] = []
    current: list[str] = []
    last_y: float | None = None
    for w in inside:
        if last_y is None or abs(w[1] - last_y) < SAME_LINE_TOLERANCE:
            current.append(w[4])
        else:
            lines.append(current)
            current = [w[4]]
        last_y = w[1]
    if current:
        lines.append(current)

    return " ".join(" ".join(line) for line in lines).strip()


def _contains(parent: FigureBox, child: FigureBox) -> bool:
    """子框是否落在父框内部（留出浮点误差）。"""
    t = CONTAIN_TOLERANCE
    return (parent.x0 <= child.x0 + t and parent.y0 <= child.y0 + t
            and parent.x1 >= child.x1 - t and parent.y1 >= child.y1 - t)


def build_structure(page: pymupdf.Page) -> tuple[list[FigureBox], dict[str, int]]:
    """还原整张图的结构，返回（所有带名模块框，统计数据）。

    流程：
        1. 取所有矩形 -> 模块框候选
        2. 每个框填入框内文字 -> 模块名
        3. 按包含关系建立父子层级
        4. 丢掉没有名字的框（容器框本身不产生信息）
    """
    boxes = get_module_boxes(page)
    named = [b for b in boxes if _text_in_box(page, b)]

    # 先算包含关系（这一步不需要标签，纯几何）
    contained_map: dict[int, list[FigureBox]] = {}
    for parent in named:
        contained_map[id(parent)] = sorted(
            [c for c in named
             if c is not parent and _contains(parent, c) and c.area < parent.area],
            key=lambda c: c.area,
        )

    # 只保留「直接子」：如果 A 包住 B、B 包住 C，那 A 的直接子里不能有 C。
    # 不筛的话 C 会在树里出现两遍（A 下面一次、B 下面一次）。
    for parent in named:
        kids = contained_map[id(parent)]
        parent.children = [
            k for k in kids
            if not any(o is not k and _contains(o, k) for o in kids)
        ]

    # 再按「由内向外」重算标签：先算叶子，父标签排除掉所有后代覆盖的文字。
    # 这样 ARM Cortex-M3 的标签就只是它自己，不会带上 TPIU / NVIC / SWD。
    def descendants(box: FigureBox) -> list[FigureBox]:
        out: list[FigureBox] = []
        for c in box.children:
            out.append(c)
            out.extend(descendants(c))
        return out

    def relabel(box: FigureBox) -> None:
        for c in box.children:
            relabel(c)
        box.label = _text_in_box(page, box, exclude=descendants(box))

    top_level: list[FigureBox] = []
    for box in named:
        has_parent = any(box in p.children for p in named if p is not box)
        if not has_parent:
            relabel(box)
            top_level.append(box)

    drawings = page.get_drawings()
    stats = {
        "rect_items": len([d for d in drawings
                           if "re" in [i[0] for i in d["items"]]
                           or "qu" in [i[0] for i in d["items"]]]),
        "line_items": sum(1 for d in drawings for i in d["items"] if i[0] == "l"),
        "curve_items": sum(1 for d in drawings for i in d["items"] if i[0] == "c"),
        "named_boxes": len(named),
        "top_level": len(top_level),
    }
    return top_level, stats


def find_caption(page: pymupdf.Page) -> tuple[str, str]:
    """找图注，比如「图1-1 系统框图」。返回（图号，图名）。"""
    for line in page.get_text().splitlines():
        m = CAPTION_RE.search(line)
        if m:
            return m.group(1).replace(" ", ""), m.group(2).strip()
    return "", ""


def spatial_columns(top_level: list[FigureBox], gap: float = 30.0
                    ) -> list[list[FigureBox]]:
    """按 x 坐标把叶子模块聚成若干「列」。

    为什么需要：架构图里同一条总线上的外设总是排成一竖列。
    比如 CH32F103 这张图：
        x≈176 那一列是 GPIOA/GPIOB/.../TIM1/SPI1/USART1  -> APB2
        x≈385 那一列是 TIM2/TIM3/.../USART2/.../bxCAN/DAC -> APB1
    只给模型一张扁平清单，它答不出「GPIOA 挂在哪条总线」；给了列，它就能看懂布局。

    gap：两列的 x 间距超过这个值就认为换列了
    """
    leaves: list[FigureBox] = []

    def collect(box: FigureBox) -> None:
        if box.children:
            for c in box.children:
                collect(c)
        elif box.label:
            leaves.append(box)

    for b in top_level:
        collect(b)

    columns: list[list[FigureBox]] = []
    for box in sorted(leaves, key=lambda b: b.x0):
        placed = False
        for col in columns:
            # 用「列内框的平均左边界」作为该列的代表位置
            avg_x = sum(b.x0 for b in col) / len(col)
            if abs(box.x0 - avg_x) <= gap:
                col.append(box)
                placed = True
                break
        if not placed:
            columns.append([box])

    for col in columns:
        col.sort(key=lambda b: b.y0)
    return [c for c in columns if len(c) >= 2]


def render_structure_text(top_level: list[FigureBox], source: str, page_no: int,
                          label: str = "", caption: str = "") -> str:
    """把还原出来的结构拼成一段大模型能直接读的文本。

    这是最终要喂给 LLM 的东西 —— 它不是 OCR 出来的描述，
    而是从坐标里读出来的事实，所以不会出现「模型脑补的连线」。
    """
    lines: list[str] = []
    lines.append(f"【{label} {caption}】 来源：{source} 第 {page_no} 页")
    lines.append("结构层级（缩进表示包含关系）：")

    def walk(box: FigureBox, depth: int) -> None:
        indent = "    " * depth
        lines.append(f"{indent}- {box.label}")
        for child in box.children:
            walk(child, depth + 1)

    for box in top_level:
        walk(box, 1)

    # 再补一份「平铺模块清单」——便于模型做枚举类回答
    flat: list[str] = []
    for box in top_level:
        flat.append(box.label)

        def collect(b: FigureBox) -> None:
            for c in b.children:
                flat.append(c.label)
                collect(c)

        collect(box)
    seen: set[str] = set()
    uniq_flat = [x for x in flat if not (x in seen or seen.add(x))]
    lines.append(f"图中出现的模块共 {len(uniq_flat)} 个：{'、'.join(uniq_flat)}")

    # 空间布局：同一竖列通常属于同一条总线，这是「看懂框图」的关键信息
    columns = spatial_columns(top_level)
    if columns:
        lines.append("")
        lines.append("空间布局（按从左到右的竖列分组，同一列通常挂在同一条总线上）：")
        for i, col in enumerate(columns, start=1):
            names = "、".join(b.label for b in col)
            lines.append(f"  第 {i} 列（{len(col)} 个，x≈{col[0].x0:.0f}）：{names}")

    return "\n".join(lines)


def render_page_png(doc: pymupdf.Document, page_no: int, dpi: int = 150
                    ) -> tuple[bytes, str]:
    """把整页渲染成 PNG 并返回字节 + base64 字符串。

    这是给**视觉模型**（DeepSeek deepseek-v4-flash-vision-exp 等）用的补充证据。
    注意它不是主方案，只在问题涉及「图里某个具体细节」时才带上。

    dpi=150 的取值理由：
      - 太低（72）：框内小字糊掉，视觉模型读不出模块名
      - 太高（300+）：图片 token 不增加（DeepSeek 会把图缩到约 800x800 再算，
        一张上限 384 token），但 base64 体积变大、请求变慢，纯浪费
    """
    page = doc[page_no - 1]
    pix = page.get_pixmap(dpi=dpi)
    png_bytes = pix.tobytes("png")
    return png_bytes, base64.b64encode(png_bytes).decode("utf-8")


def scan_pages(pdf_path: str | Path) -> list[dict]:
    """扫一遍整份 PDF，报告每页的性质（该页有没有需要结构还原的图）。"""
    doc = pymupdf.open(str(pdf_path))
    rows: list[dict] = []
    for i, page in enumerate(doc):
        drawings = page.get_drawings()
        rects = sum(1 for d in drawings
                    if "re" in [k[0] for k in d["items"]]
                    or "qu" in [k[0] for k in d["items"]])
        lines = sum(1 for d in drawings for k in d["items"] if k[0] == "l")
        images = len(page.get_images(full=True))
        text_len = len(page.get_text().strip())
        rows.append({
            "page": i + 1,
            "rect_items": rects,
            "line_items": lines,
            "bitmap_count": images,
            "text_chars": text_len,
            # 判断依据：有很多矩形 + 很多连线 => 大概率是矢量框图/表格，不是普通正文
            "likely_diagram": rects >= 10 and lines >= 50,
            # 文本层为空且有整页大图 => 扫描件，那种才需要 OCR
            "needs_ocr": text_len < 20 and images >= 1,
        })
    doc.close()
    return rows


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="从 PDF 的矢量图元还原架构框图结构（不走 OCR）")
    parser.add_argument("--pdf", default="datasheets/CH32F103_Datasheet_CN.pdf",
                        help="PDF 路径")
    parser.add_argument("--page", type=int, default=3,
                        help="要还原的页码，从 1 开始")
    parser.add_argument("--scan", action="store_true",
                        help="扫描整份 PDF，列出哪些页疑似矢量框图")
    parser.add_argument("--png", action="store_true",
                        help="额外把该页渲染成 PNG，打印大小信息")
    args = parser.parse_args()

    if args.scan:
        rows = scan_pages(args.pdf)
        print(f"{'页':>4} {'矩形':>5} {'连线':>5} {'位图':>5} {'文字数':>7}  判定")
        for r in rows:
            tag = []
            if r["likely_diagram"]:
                tag.append("矢量框图")
            if r["needs_ocr"]:
                tag.append("需 OCR")
            print(f"{r['page']:>4} {r['rect_items']:>5} {r['line_items']:>5} "
                  f"{r['bitmap_count']:>5} {r['text_chars']:>7}  {'/'.join(tag) or '正文'}")
        return

    doc = pymupdf.open(args.pdf)
    page = doc[args.page - 1]
    label, caption = find_caption(page)
    top_level, stats = build_structure(page)

    print("=== 图元统计 ===")
    for k, v in stats.items():
        print(f"  {k:>14}: {v}")
    print(f"  {'caption':>14}: {label} {caption}")
    print()
    print(render_structure_text(top_level, Path(args.pdf).name, args.page,
                                label=label, caption=caption))

    if args.png:
        png_bytes, b64 = render_page_png(doc, args.page)
        print()
        print(f"渲染 PNG：{len(png_bytes) / 1024:.0f} KB，"
              f"base64 后 {len(b64) / 1024:.0f} KB")

    doc.close()


if __name__ == "__main__":
    _main()
