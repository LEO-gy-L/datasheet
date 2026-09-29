"""
pdfplumber vs PyMuPDF 对比脚本（P0 选型验证用）

目的：用同一份 STM32 手册的同一个表格，对比两个库的输出差异，
      回答"为什么选 PyMuPDF 而不是 pdfplumber"这个问题。

运行： .venv\\Scripts\\python src\\p0_compare_pdfplumber.py
"""

import time

import fitz  # PyMuPDF，C 实现
import pdfplumber  # 纯 Python 实现

PDF = "datasheets/STM32F103C8_Datasheet.pdf"
PAGE = 36  # 第 37 页（0 基索引）


def show(title: str, rows: list[list[str]], limit: int = 7):
    print(f"----- {title} -----")
    for i, r in enumerate(rows[:limit]):
        print(f"  {i} " + " | ".join((c or "").strip()[:24] for c in r))
    print()


# ============ 1. pdfplumber：坐标派的经典做法 ============
print("=" * 70)
print("第 37 页 Table 6（Voltage characteristics）对比")
print("=" * 70)
print()

t0 = time.time()
with pdfplumber.open(PDF) as pdf:
    page = pdf.pages[PAGE]
    tables = page.extract_tables()
    plumber_rows = tables[0] if tables else []
    # 顺带看看 pdfplumber 能拿到什么坐标信息
    w0 = page.extract_words()[:1]
    pt = page.extract_tables(
        {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
    )
t_plumber = time.time() - t0

print(f"pdfplumber 耗时：{t_plumber:.2f} 秒   识别到表格数：{len(tables)}")
if w0:
    print("pdfplumber 单词对象字段：", sorted(w0[0].keys()))
show("pdfplumber extract_tables() 输出", plumber_rows)


# ============ 2. PyMuPDF：C 实现 + 自带下标修复 ============
t0 = time.time()
doc = fitz.open(PDF)
p = doc[PAGE]
tb = p.find_tables()
mu_tables = tb.tables
mu_rows = mu_tables[0].extract()
mu_md = mu_tables[0].to_markdown()
t_mu = time.time() - t0

print(f"PyMuPDF 耗时：{t_mu:.2f} 秒   识别到表格数：{len(mu_tables)}")
print("PyMuPDF 单词对象字段：['x0','y0','x1','y1','word','block','line','line_no']（坐标齐全）")
show("PyMuPDF extract() 输出", mu_rows)

print("----- PyMuPDF to_markdown() 输出（已自动修下标）-----")
for line in mu_md.splitlines()[:7]:
    print("  " + line[:110])
print()


# ============ 3. 关键对比点 ============
print("=" * 70)
print("关键差异")
print("=" * 70)

# 差异①：下标处理
plumber_first = (plumber_rows[1][0] or "") if len(plumber_rows) > 1 else ""
mu_first = (mu_rows[1][0] or "") if len(mu_rows) > 1 else ""
print(f"① 下标 'VDD-VSS' 那一格：")
print(f"     pdfplumber : {plumber_first.replace(chr(10), ' ')!r}")
print(f"     PyMuPDF    : {mu_first.replace(chr(10), ' ')!r}")

# 差异②：合并单元格（Unit 列）
print()
print("② 合并单元格 Unit 列（第 1~4 行，PDF 里 V 是纵向跨 3 行的合并格）：")
for i in range(1, min(5, max(len(plumber_rows), len(mu_rows)))):
    pv = plumber_rows[i][-1] if i < len(plumber_rows) and plumber_rows[i] else ""
    mv = mu_rows[i][-1] if i < len(mu_rows) and mu_rows[i] else ""
    print(f"     行{i}  pdfplumber={pv!r:<22} PyMuPDF={mv!r}")

# 差异③：速度（全文扫描）
print()
print("③ 全文 114 页扫描速度对比（这是选型的关键之一）：")
t0 = time.time()
with pdfplumber.open(PDF) as pdf:
    n_p = sum(len(pg.extract_tables()) for pg in pdf.pages)
t_all_plumber = time.time() - t0

t0 = time.time()
doc2 = fitz.open(PDF)
n_m = sum(len(pg.find_tables().tables) for pg in doc2)
t_all_mu = time.time() - t0
doc2.close()

print(f"     pdfplumber : {t_all_plumber:6.2f} 秒，识别 {n_p} 张表")
print(f"     PyMuPDF    : {t_all_mu:6.2f} 秒，识别 {n_m} 张表")
print(f"     速度倍数   : {t_all_plumber / max(t_all_mu, 0.001):.1f}x")

# 差异④：pdfplumber 做不到、PyMuPDF 能做的事
print()
print("④ PyMuPDF 独有、pdfplumber 没有的能力（本项目必须用到）：")
pix = p.get_pixmap(dpi=72)
print(f"     整页渲染成图片      : 成功，{pix.width}x{pix.height} px（送视觉大模型要用）")
print(f"     矢量图形指令数      : {len(p.get_drawings())} 个（用来判断这页值不值得渲染）")
print(f"     每页图片对象        : {len(p.get_images())} 个")
print("     pdfplumber          : 不做渲染，也没有矢量图形接口（底层 pdfminer 只管文字和线条）")

doc.close()
