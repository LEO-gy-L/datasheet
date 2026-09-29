# -*- coding: utf-8 -*-
"""
P0 第 2 步：伪表过滤
=====================

【这一步要解决的问题】
上一版（v3）把 PDF 里所有被 PyMuPDF 认成"表"的东西都输出了 —— 179 张。
但其中 99 张根本不是表，而是**图里面的标注框**：
  - 第 22 页 LQFP100 引脚图：每个引脚编号框被当成一张"表"（1 行 2 列，内容是 `Col1 | 1`）
  - 第 90/95/96/98/100 页封装尺寸图：尺寸字母 `aaa / bbb / ØeeeM / C B A / D`
  - 第 11/12 页框图：器件总览框图里的 SRAM / PLL 标签
  - 第 46/51/52/71 页曲线图与时序图：坐标轴刻度和图注

这些东西如果混进向量库，用户问"引脚定义"会被一堆 `Col1 | 3` 污染，检索质量崩塌。

【为什么"有没有 Table N 标题"是最好的判据】
实测统计（本项目 114 页 / 179 张表）：
  | 特征                | 有 Table N 标题 | 无标题 |
  |---------------------|-----------------|--------|
  | 表数量              | 80              | 99     |
  | 与矢量图形重叠比例  | **全部 = 0**    | 44 张 > 0 |
  | 列数分布            | 7/6/3/4/13 列为主 | **70 张是 2 列** |

  两者完全分离：真表标题里有编号、且从不和图形重合；
  伪表没有编号、且大多是 2 列以内的碎片。

【但不能只靠"有没有标题"一条规则】
  理由：跨页续表（Table 21 的续表在第 52 页）上方是没有标题的，
        一刀切会把它误杀。所以本脚本用**多条规则依次否决**，
        并且对"不确定"的表一律**保留 + 报警**，绝不黑箱删数据。

【运行方式】（在项目根目录 datasheet 下）
  uv run python src\\p0_2_filter_tables.py
  uv run python src\\p0_2_filter_tables.py --pdf datasheets/ATmega328P_Datasheet.pdf

【输出】
  data/tables_v4/<PDF名>/page_XXX.md   保留的真表
  data/tables_v4/<PDF名>/_filtered_out.md   被剔除的清单（可审计，方便你自己复核）
"""

import re
import statistics
import sys
from pathlib import Path

# 保证 Windows 控制台也能正常显示中文
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 把 src 目录加进模块搜索路径，这样才能 import 上一版的脚本
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import pymupdf
except ImportError:  # 老版本 PyMuPDF 只有 fitz 这个名字
    import fitz as pymupdf

# 复用 v3 已经写好的清洗与修复逻辑（不重复造轮子）
from p0_1_tables_v3 import (
    table_to_markdown,
    find_title_by_coords,
    PLACEHOLDER_RE,
)


# ------------------------------------------------------------------
# 配置区：所有阈值集中在这里，方便你自己调参看效果
# ------------------------------------------------------------------
# 本文件已归档到 src/legacy/，比原来多一层目录，项目根因此是 parents[2]
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PDF = ROOT / "datasheets" / "STM32F103C8_Datasheet.pdf"
OUT_ROOT = ROOT / "data" / "tables_v4"

DRAW_OVERLAP_MAX = 0.20   # 与矢量图形重叠超过 20% -> 判定为"图的一部分"
TINY_MAX_ROWS = 2         # 行数 <= 2
TINY_MAX_COLS = 2         # 列数 <= 2  （两者同时满足 -> 判定为图内标签框）
PLACEHOLDER_MAX_RATIO = 0.40  # 表头里 Col1/Col2 这类占位名超过 40% -> 表头识别失败
SHORT_CELL_MAX_LEN = 5.0  # 单元格平均字符数 < 5 -> 内容太碎，不是表

NEAR_PAGE_TOP_PT = 80.0   # 表格上边框离页顶不足 80pt -> 可能是跨页续表，要报警
                          # （ATmega 手册页眉本身就占 87pt，阈值定 90 会刷屏假警报）
BIG_MIN_ROWS = 5          # 行数 >= 5 且列数 >= 3 却被判伪 -> 报警（可能是误杀真表）
BIG_MIN_COLS = 3

# 【重要教训】下面两个常量是踩过坑才定下来的，别随便调大。
#
#   第一版规则里我写的是"只有一行 -> 剔除"，在 STM32 手册上跑得很漂亮（零误杀），
#   结果换到 ATmega328P 手册上，一下杀掉了 72 张**寄存器位定义表**：
#     | CLKPCE | – | – | – | CLKPS3 | CLKPS2 | CLKPS1 | CLKPS0 |
#     | – | – | – | – | – | – | INT1 | INT0 |
#   这是 AVR 手册描述 8 位寄存器的标准格式 —— 天然就是"1 行 8 列"，
#   而且是硬件工程师查阅频率最高的内容。
#   STM32 手册恰好不用这种写法（它用多行表描述寄存器位），
#   所以我照着 STM32 定出来的规则是**过拟合**的。
#
#   教训：清洗/过滤规则绝不能只在一份样本上调参，
#         必须至少拿两种排版风格完全不同的手册交叉验证。
#
# 单行表只有在"又窄"的时候才是碎片；宽单行表（>=4列）大概率是寄存器位表，必须留。
SINGLE_ROW_MAX_COLS = 3

# "内容平均长度过短"只对多行表生效。
# 单行寄存器表的单元格本来就短（"INT0"、"–"），用长度卡会把它们误杀。
FRAGMENT_MIN_ROWS = 5


# ==================================================================
# 特征计算
# ==================================================================
def calc_draw_ratio(page, table, drawings_cache: list | None = None) -> float:
    """
    算"表格区域被矢量图形覆盖的比例"。

    为什么这个指标有用：
      PDF 里没有"图"这个对象，图是用一堆画线指令画出来的。
      PyMuPDF 的 get_drawings() 能把那些画线指令还原出来。
      如果一个"表"的矩形范围里塞满了画线指令 —— 那它大概率是图的一部分，
      而不是真正的数据表（真的数据表只有横竖网格线和文字）。

    注意：带填充色的矩形（fill 不是 None）不计入。
          因为表格自身的单元格底色也会被算成 drawing，那是正常的。
    """
    drawings = drawings_cache if drawings_cache is not None else page.get_drawings()
    x0, y0, x1, y1 = table.bbox
    area = (x1 - x0) * (y1 - y0)
    if area <= 0:
        return 0.0

    overlap = 0.0
    for d in drawings:
        if d.get("fill") is not None:
            continue
        r = d["rect"]
        ox = max(0.0, min(x1, r.x1) - max(x0, r.x0))
        oy = max(0.0, min(y1, r.y1) - max(y0, r.y0))
        if ox > 0 and oy > 0:
            overlap += ox * oy

    # 封顶到 100%：曲线图里成百上千条短线矩形会重复累加，
    # 直接相加能算出 213% 这种没法看的数字，而这里语义是"覆盖率"。
    return min(overlap / area, 1.0)


def parse_md_rows(md: str) -> list[list[str]]:
    """把 Markdown 表格文本还原成二维列表（跳过分隔线 |---|---|）。"""
    rows = []
    for line in md.splitlines():
        line = line.strip()
        if not line or re.fullmatch(r"\|[\s\-:|]+\|", line):
            continue
        rows.append([c.strip() for c in line.strip("|").split("|")])
    return rows


def calc_features(page, table, raw_md: str, clean_md: str,
                  drawings_cache: list | None = None) -> dict:
    """
    把判断一张表真假所需要的所有特征一次性算出来。

    【为什么必须同时传 raw_md 和 clean_md】
      占位名（Col1 / Col2）比例必须在**清洗前**的原始输出上算。
      因为 v3 的 drop_placeholder_columns 会把这些占位列整列删掉，
      等清洗完再算，比例永远是 0 —— 这条规则就废了。
      实测就栽过：第 11 页框图里的 SRAM/PLL 伪表（4行×4列）
      原始表头是 `SRAM 20KB | Col2 | Col3 | Col4`（占位名占 75%），
      清洗后只剩 `SRAM 20KB`，于是它一路过关被当成真表保留下来。

      而平均单元格字数要在清洗后的文本上算才准
      （原始文本里混着 `<br>`、`~~`、`**` 这些标签会虚增长度）。
    """
    raw_rows = parse_md_rows(raw_md)
    clean_rows = parse_md_rows(clean_md)
    grid = [list(r.cells) for r in table.rows]

    clean_cells = [c for r in clean_rows for c in r if c]

    header = raw_rows[0] if raw_rows else []
    placeholder_ratio = (
        sum(1 for c in header if PLACEHOLDER_RE.match(c)) / len(header)
        if header else 0.0
    )

    return {
        "n_rows": len(grid),
        "n_cols": len(grid[0]) if grid else 0,
        "n_text_rows": len(clean_rows),
        "placeholder_ratio": round(placeholder_ratio, 2),
        "avg_cell_len": round(
            statistics.mean([len(c) for c in clean_cells]), 1) if clean_cells else 0.0,
        "draw_ratio": round(calc_draw_ratio(page, table, drawings_cache), 2),
        "y_top": round(table.bbox[1], 1),
    }


# ==================================================================
# 判定逻辑：按顺序否决，任何一条命中就被剔除
# ==================================================================
def judge(title: str, f: dict) -> tuple[bool, str]:
    """
    返回 (是否保留, 理由)。

    顺序很重要 —— 先短路最强信号，再逐级兜底。
    """
    # 0. 最强信号：表格上方有 "Table N." 编号标题 -> 一定是真表，直接留下
    #    实测 80 张有标题的表全部是真表，且它们的图形重叠率都是 0。
    if title:
        return True, f"有编号标题 {title[:46]}"

    # 1. 和矢量图形大面积重叠 -> 它是图里的一部分，不是数据表
    if f["draw_ratio"] > DRAW_OVERLAP_MAX:
        return False, f"图形重叠 {f['draw_ratio']*100:.0f}%（图的一部分）"

    # 2. 又小又窄 -> 图内的标签框（典型：引脚图里的 `| Col1 | 3 |`）
    if f["n_rows"] <= TINY_MAX_ROWS and f["n_cols"] <= TINY_MAX_COLS:
        return False, f"尺寸过小 {f['n_rows']}行×{f['n_cols']}列（图内标签框）"

    # 3. 表头一半以上是 Col1/Col2 占位名 -> PyMuPDF 压根没认出表头
    if f["placeholder_ratio"] > PLACEHOLDER_MAX_RATIO:
        return False, f"表头占位名占 {f['placeholder_ratio']*100:.0f}%（表头识别失败）"

    # 4. 只有一行"且很窄" -> 不构成表
    #    注意这里必须同时限制列数：1 行 8 列的宽表是 AVR 风格的寄存器位定义表，
    #    是真表，绝不能杀（见文件顶部 SINGLE_ROW_MAX_COLS 处的教训说明）。
    if f["n_text_rows"] <= 1 and f["n_cols"] <= SINGLE_ROW_MAX_COLS:
        return False, f"单行且窄 {f['n_cols']}列（不构成表）"

    # 5. 多行但内容平均长度过短 -> 尺寸标注碎片（如 `aaa` / `Ø` / `C B A`）
    #    同样只对多行表生效：单行寄存器表的单元格天然就短。
    if f["n_text_rows"] >= FRAGMENT_MIN_ROWS and f["avg_cell_len"] < SHORT_CELL_MAX_LEN:
        return False, f"内容过碎 平均{f['avg_cell_len']}字符（尺寸标注）"

    # 走完所有规则还活着 -> 保留，但会在报告里标出来请你复核
    return True, "未命中任何剔除规则（建议人工复核）"


def safety_warnings(f: dict) -> list[str]:
    """
    误杀报警。宁可在报告里啰嗦，也不能悄悄删掉可能是真表的东西。
    """
    warns = []
    if f["y_top"] < NEAR_PAGE_TOP_PT:
        warns.append(f"紧贴页顶({f['y_top']:.0f}pt)，可能是跨页续表")
    if f["n_rows"] >= BIG_MIN_ROWS and f["n_cols"] >= BIG_MIN_COLS:
        warns.append(f"规模较大({f['n_rows']}行×{f['n_cols']}列)，请确认是否误杀")
    return warns


# ==================================================================
# 主流程
# ==================================================================
def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="P0 第2步：过滤伪表")
    ap.add_argument("--pdf", type=Path, default=DEFAULT_PDF, help="PDF 路径")
    ap.add_argument("--out", type=Path, default=OUT_ROOT, help="输出根目录")
    ap.add_argument("--probe", action="store_true",
                    help="只做统计不改变 outputs（本脚本默认就写盘，此开关保留兼容）")
    args = ap.parse_args()

    if not args.pdf.exists():
        print(f"找不到 PDF：{args.pdf.resolve()}")
        print("请确认你在项目根目录 datasheet 下运行这条命令")
        return

    if not (Path(__file__).resolve().parent / "p0_1_tables_v3.py").exists():
        print("找不到 src/p0_1_tables_v3.py，本脚本依赖它，请确认文件还在")
        return

    out_dir = args.out / args.pdf.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(args.pdf)

    kept_pages: dict[int, list[str]] = {}
    dropped: list[tuple[int, int, dict, str, list[str]]] = []
    total = 0
    keep_by_title = 0
    keep_by_rule = 0

    print("=" * 74)
    print(f"伪表过滤：{args.pdf.name}  共 {doc.page_count} 页")
    print("=" * 74)

    for pi in range(doc.page_count):
        page = doc[pi]
        page_no = pi + 1
        tables = list(page.find_tables().tables)
        if not tables:
            continue

        # 每页只算一次矢量图形，50 张表的页面也不会重复计算
        drawings_cache = page.get_drawings()

        for t_index, table in enumerate(tables, start=1):
            total += 1

            title = find_title_by_coords(page, table)
            # 原始输出，用于算占位名比例等"清洗会破坏"的判据
            raw_md = table.to_markdown()
            # v3 清洗修复后的输出，用于最终落盘和算平均字数
            title_md, md = table_to_markdown(page, table)
            # table_to_markdown 内部有回退取标题的逻辑，两个来源取其一
            title = title_md or title

            f = calc_features(page, table, raw_md, md, drawings_cache)
            keep, reason = judge(title, f)

            if keep:
                lines = [f"[来源] {args.pdf.name} 第 {page_no} 页 表 {t_index}"]
                if title:
                    lines.append(f"[标题] {title}")
                lines.append(md)
                kept_pages.setdefault(page_no, []).append("\n".join(lines))
                if title:
                    keep_by_title += 1
                else:
                    keep_by_rule += 1
                    print(f"  [复核] 第{page_no}页 表{t_index} 未带标题但被保留 "
                          f"({f['n_rows']}行×{f['n_cols']}列)")
            else:
                warns = safety_warnings(f)
                dropped.append((page_no, t_index, f, reason, warns))
                if warns:
                    print(f"  [警告] 第{page_no}页 表{t_index} 被剔除但存疑："
                          f"{reason}；{'；'.join(warns)}")

    for page_no, chunks in sorted(kept_pages.items()):
        (out_dir / f"page_{page_no:03d}.md").write_text(
            "\n\n".join(chunks), encoding="utf-8")

    report = ["# 被剔除的伪表清单（可审计）", ""]
    report.append(f"- PDF：{args.pdf.name}")
    report.append(f"- 总表数：{total}")
    report.append(f"- 保留：{keep_by_title + keep_by_rule}  "
                  f"（有标题 {keep_by_title} + 无标题但通过规则 {keep_by_rule}）")
    report.append(f"- 剔除：{len(dropped)}")
    report.append("")
    report.append("| 页 | 表 | 行×列 | 图形重叠 | 表头占位名 | 平均字数 | 剔除理由 | 存疑提示 |")
    report.append("|---|---|---|---|---|---|---|---|")
    for page_no, t_index, f, reason, warns in dropped:
        report.append(
            f"| {page_no} | {t_index} | {f['n_rows']}×{f['n_cols']} | "
            f"{f['draw_ratio']*100:.0f}% | {f['placeholder_ratio']*100:.0f}% | "
            f"{f['avg_cell_len']} | {reason} | {'；'.join(warns) or '-'} |")
    (out_dir / "_filtered_out.md").write_text("\n".join(report), encoding="utf-8")

    print("\n" + "=" * 74)
    print("过滤结果")
    print("=" * 74)
    print(f"  表格总数     : {total}")
    print(f"  保留         : {keep_by_title + keep_by_rule}  "
          f"(其中 {keep_by_title} 张靠 Table N 标题判定)")
    print(f"  剔除         : {len(dropped)}")
    if 'total' in dir() and total:
        print(f"  伪表占比     : {100.0 * len(dropped) / total:.1f}%")
    print(f"  输出目录     : {out_dir.resolve()}")

    reason_count: dict[str, int] = {}
    for _, _, _, reason, _ in dropped:
        key = reason.split("（")[0].split("(")[0][:24]
        reason_count[key] = reason_count.get(key, 0) + 1
    print("\n  剔除理由分布：")
    for k, v in sorted(reason_count.items(), key=lambda x: -x[1]):
        print(f"    {k:<26s} {v} 张")

    warned = [d for d in dropped if d[4]]
    if warned:
        print(f"\n  有 {len(warned)} 张表的剔除值得你自己再看一眼，清单见 _filtered_out.md")
    else:
        print("\n  没有出现存疑的剔除（未触发跨页续表/规模过大报警）")


if __name__ == "__main__":
    main()
