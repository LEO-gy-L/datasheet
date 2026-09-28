# -*- coding: utf-8 -*-
"""
P0 第 1 步：把 PDF 里的表格还原成干净的 Markdown

作用：
  1. 扫描 PDF 的每一页，找出所有表格
  2. 用 to_markdown() 还原行列（这个方法会自动把下标归位，比 extract() 好很多）
  3. 做一轮字符清洗（去 HTML 标签、统一横线、去非断空格）
  4. 把结果写到 data/tables/ 目录，同时打印一份样本供你检查

运行方式（在 datasheet 目录下）：
  .venv\\Scripts\\python src\\p0_1_tables.py
"""

import re
from pathlib import Path

import fitz  # PyMuPDF，这是我们用来读 PDF 的库

# ------------------------------------------------------------------
# 配置区：想换文件、换页码，只改这里
# ------------------------------------------------------------------
PDF_PATH = Path("datasheets/STM32F103C8_Datasheet.pdf")
OUT_DIR = Path("data/tables")          # 表格结果输出到这个目录
SAMPLE_PAGE = 37                        # 想打印哪一页的表格给你看（PDF 上的页码，不是下标）
ENABLE_SUBSCRIPT_SPACE_FIX = False      # 可选规则，先关掉，第 2 版再开


# ------------------------------------------------------------------
# 清洗规则：每条规则都写成一个小函数，方便单独开关和调试
# ------------------------------------------------------------------
def normalize_dashes(text: str) -> str:
    """
    把所有"看起来像横线"的字符统一成键盘上的 ASCII 减号 '-'。

    为什么必须做：
        PDF 里数值用的是 en dash '–'(U+2013)，符号列用的是 minus '−'(U+2212)，
        还有 hyphen '‐'、non-breaking hyphen '‑' 等变体。
        用户在输入框里敲的是 ASCII '-'，不做归一化的话，检索永远匹配不上。
    """
    # 这三个字符长得几乎一样，但编码完全不同
    for ch in ["\u2013", "\u2212", "\u2010", "\u2011", "\u2014", "\u2015"]:
        text = text.replace(ch, "-")
    return text


def remove_html_tags(text: str) -> str:
    """
    去掉 PyMuPDF 生成的 HTML 标记。

    to_markdown() 会把单元格内的换行写成 <br>，把斜体/下划线写成 _xxx_。
    我们的目标是纯文本，这些标记对向量检索是噪声。
    """
    text = text.replace("<br>", " ").replace("<br/>", " ").replace("<br />", " ")
    text = re.sub(r"</?[a-zA-Z][^>]*>", " ", text)   # 兜底：去掉任意 HTML 标签
    text = text.replace("_", " ")                     # 去掉 markdown 斜体标记
    return text


def normalize_spaces(text: str) -> str:
    """
    空格归一化。
      - 非断空格 \\xa0 换成普通空格（这个字符最隐蔽，会让 "Table 6" 粘成 "Table\\xa06"）
      - 连续空格折叠成一个
      - 去掉每行首尾空格
    """
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def fix_dash_spacing(text: str) -> str:
    """
    修正横线两侧的空格。
    PDF 里常出现 "VSS− 0.3" 这种（横线紧跟前一个词、离后一个词远），
    统一成 "VSS - 0.3"，读起来正常，分词也更准。
    """
    text = re.sub(r"\s*-\s*", " - ", text)   # 无论原来怎么排，统一成 " - "
    text = re.sub(r" +\- +", " - ", text)    # 折叠多余的空格
    return text


def fix_subscript_space(text: str) -> str:
    """
    【可选规则】在"连续大写字母 + 小写字母"之间补空格。
    例：VDDpower pins -> VDD power pins

    为什么默认关掉：
        这条规则有风险，可能把 "External" 错切成 "E xternal"。
        虽然我用"前面必须有两个以上大写字母"做了限制，但仍需你人眼确认后再开。
    """
    return re.sub(r"(?<=[A-Z]{2})(?=[a-z])", " ", text)


def clean_cell(text: str) -> str:
    """按固定顺序跑一遍上面的规则。顺序不能乱：先去标签，再统一字符，最后调空格。"""
    if text is None:
        return ""
    text = remove_html_tags(text)
    text = normalize_dashes(text)
    text = normalize_spaces(text)
    text = fix_dash_spacing(text)
    if ENABLE_SUBSCRIPT_SPACE_FIX:
        text = fix_subscript_space(text)
    return text


# ------------------------------------------------------------------
# 表格还原
# ------------------------------------------------------------------
def table_to_markdown(page, table) -> str:
    """
    把一个 PyMuPDF 表格对象转成清洗过的 Markdown 文本。

    关键点：用 table.to_markdown() 而不是 table.extract()
      - to_markdown() 会按字号识别上下标，把 "V − V DD SS" 正确还原成 "VDD − VSS"
      - extract() 只给单元格字符串，上下标顺序是乱的
    """
    raw = table.to_markdown()
    lines = raw.splitlines()

    cleaned_lines = []
    for line in lines:
        if not line.strip():
            continue
        # Markdown 表格的一行形如：| Symbol | Ratings | Min | Max | Unit |
        cells = line.strip().strip("|").split("|")
        cells = [clean_cell(c) for c in cells]
        cleaned_lines.append("| " + " | ".join(cells) + " |")

    # 去掉 Markdown 的第二行分隔线 |---|---|，它对检索没意义
    cleaned_lines = [l for l in cleaned_lines if not re.fullmatch(r"\|[\s\-:|]+\|", l)]

    return "\n".join(cleaned_lines)


def main() -> None:
    if not PDF_PATH.exists():
        print(f"找不到 PDF：{PDF_PATH.resolve()}")
        print("请确认你在 datasheet 目录下运行这条命令")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(PDF_PATH)

    total_tables = 0
    pages_with_tables = []

    print("=" * 60)
    print(f"开始扫描：{PDF_PATH.name}  共 {doc.page_count} 页")
    print("=" * 60)

    for page_index in range(doc.page_count):
        page = doc[page_index]
        page_no = page_index + 1          # PDF 页码从 1 开始
        tables = list(page.find_tables().tables)

        if not tables:
            continue

        pages_with_tables.append(page_no)
        page_chunks = []

        for t_index, table in enumerate(tables, start=1):
            md = table_to_markdown(page, table)
            # 在表格前面加一行说明，标明来源与页码 —— 检索到这块时才知道它是谁
            header = f"[来源] {PDF_PATH.name} 第 {page_no} 页 表 {t_index}"
            page_chunks.append(f"{header}\n{md}")
            total_tables += 1

        # 每页的所有表格写成一个文件
        out_file = OUT_DIR / f"page_{page_no:03d}.md"
        out_file.write_text("\n\n".join(page_chunks), encoding="utf-8")

    print(f"\n扫描完成：{len(pages_with_tables)} 页含表格，共 {total_tables} 张表")
    print(f"结果已写入：{OUT_DIR.resolve()}")
    print(f"含表格的页码（前 30 个）：{pages_with_tables[:30]}")

    # --------------------------------------------------------------
    # 打印样本，让你亲眼检查清洗效果
    # --------------------------------------------------------------
    sample_file = OUT_DIR / f"page_{SAMPLE_PAGE:03d}.md"
    if sample_file.exists():
        print("\n" + "=" * 60)
        print(f"样本：第 {SAMPLE_PAGE} 页的表格（清洗后）")
        print("=" * 60)
        print(sample_file.read_text(encoding="utf-8")[:1200])
    else:
        print(f"\n第 {SAMPLE_PAGE} 页没有表格，换一页试试（上面列出了含表格的页码）")


if __name__ == "__main__":
    main()
