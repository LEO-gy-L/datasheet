# -*- coding: utf-8 -*-
"""
⚠️【已归档，不要运行】⚠️
==========================
本文件已于 2026-09-29 废弃，从 src/ 移到 src/legacy/，原因有两个：

  1. 第 75 行那条正则写错了：本意是 [来源] / [标题]，
     却写成了 $$来源$$ / $$标题$$。而 $ 在 Python 正则里是"字符串结尾"断言，
     $$来源$$ 的含义是"结尾+结尾+来源+结尾"，永远匹配不上，
     于是 finditer() 返回空 —— 所有表格块被静默丢弃，一块都切不出来，还不报错。
     （实测产物：chunks.jsonl 共 337 块，100% 是 text，table 块 = 0）

  2. 它和 p1_1_chunk.py 写**同一个输出文件** data/chunks/<手册名>/chunks.jsonl，
     谁后跑谁覆盖谁。当时它后跑，把正确的产物盖掉了，
     导致同目录 _report.md（声称 69 个表格块）和实际数据对不上。

现在的切块工作由 src/chunk_loader.py 负责（读 data/text_v2 + data/tables_v5，
输出 data/chunks_v2/<手册名>/chunks.jsonl）。本文件保留只为留个证据，别跑它。

----- 以下为原始说明 -----
加载已解析的文本/表格 Markdown，并切成小块

为什么改数据源：
  1. 不再读原始 PDF（PyPDFLoader 会撕裂表格）
  2. 改用 P0 已清洗好的产物：
       - data/text_v1/     正文
       - data/tables_v4/   表格
  3. 表格整张保留，正文按 400 字符切
"""

import json
import re
from pathlib import Path

# ⚠️ 本文件没有 __main__ 保护 —— 只要被 import，模块级代码就会立刻跑完整条管线、
# 并往 data/chunks/<手册名>/chunks.jsonl 写盘。下面这行把"被 import"这条路堵死，
# 避免别的脚本误 import 时静默改掉产物（这个坑 QA 复核时实测复现过）。
if __name__ != "__main__":
    raise ImportError(
        "load_split.py 已废弃且会在模块级写盘，禁止 import；切块请用 src/chunk_loader.py"
    )

# ---------- 1. 路径 ----------
# 本文件已归档到 src/legacy/，比原来多一层目录，项目根因此是 parents[2]
BASE_DIR = Path(__file__).resolve().parents[2]

PDF_NAME = "STM32F103C8_Datasheet"
TEXT_DIR = BASE_DIR / "data" / "text_v1" / PDF_NAME
TABLE_DIR = BASE_DIR / "data" / "tables_v4" / PDF_NAME
OUT_DIR = BASE_DIR / "data" / "chunks" / PDF_NAME
OUT_DIR.mkdir(parents=True, exist_ok=True)

chunks: list[dict] = []


# ---------- 2. 读取正文页并按块切 ----------
TEXT_MAX_CHARS = 400      # 每块正文大约多长
TEXT_OVERLAP_CHARS = 50   # 相邻块重叠多少字，防止句子被砍断

for md_file in sorted(TEXT_DIR.glob("page_*.md")):
    raw = md_file.read_text(encoding="utf-8")
    if not raw.strip():
        continue

    # 解析我们之前写入的 [来源]/[页码] 头信息
    source = "STM32F103C8_Datasheet.pdf"
    page_no = int(re.search(r"page_(\d+)\.md$", md_file.name).group(1))

    paragraphs = [p.strip() for p in raw.split("\n\n") if p.strip()]
    buf = ""
    for para in paragraphs:
        if len(buf) + len(para) > TEXT_MAX_CHARS and buf:
            chunks.append({
                "id": f"text-p{page_no:03d}-{len(chunks):04d}",
                "type": "text",
                "source": source,
                "page": page_no,
                "title": f"第 {page_no} 页正文",
                "content": buf.strip(),
                "n_chars": len(buf.strip()),
            })
            buf = buf[-TEXT_OVERLAP_CHARS:]  # 保留重叠
        buf += "\n\n" + para if buf else para

    if buf.strip():
        chunks.append({
            "id": f"text-p{page_no:03d}-{len(chunks):04d}",
            "type": "text",
            "source": source,
            "page": page_no,
            "title": f"第 {page_no} 页正文",
            "content": buf.strip(),
            "n_chars": len(buf.strip()),
        })


# ---------- 3. 读取表格页，整张保留 ----------
# 实际格式：
#   [来源] STM32F103C8_Datasheet.pdf 第 37 页 表 1
#   [标题] Table 6. Voltage characteristics
table_re = re.compile(
    r"$$来源$$ (.*?)第 (\d+) 页 表 (\d+)\n$$标题$$ (.*?)\n(.*?)(?=\n\n$$来源$$|$)",
    re.S,
)

for md_file in sorted(TABLE_DIR.glob("page_*.md")):
    raw = md_file.read_text(encoding="utf-8").strip()
    if not raw:
        continue

    for m in table_re.finditer(raw):
        source_prefix, page_no, table_idx, title, body = m.groups()
        page_no = int(page_no)
        body = body.strip()
        if not body:
            continue
        chunks.append({
            "id": f"table-p{page_no:03d}-t{int(table_idx):02d}-{len(chunks):04d}",
            "type": "table",
            "source": f"{source_prefix.strip()}第 {page_no} 页 表 {table_idx}",
            "page": page_no,
            "title": title.strip(),
            "content": body,
            "n_chars": len(body),
        })


# ---------- 4. 写出 ----------
jsonl_path = OUT_DIR / "chunks.jsonl"
with jsonl_path.open("w", encoding="utf-8") as f:
    for c in chunks:
        f.write(json.dumps(c, ensure_ascii=False) + "\n")

# ---------- 5. 简单报告 ----------
print(f"共生成 {len(chunks)} 块")
print(f"  表格块：{sum(1 for c in chunks if c['type'] == 'table')} 块")
print(f"  正文块：{sum(1 for c in chunks if c['type'] == 'text')} 块")
print(f"输出：{jsonl_path}")

# 打印两块示例
for c in chunks[:2]:
    print("\n" + "=" * 50)
    print(f"[{c['type']}] {c['title']}（{c['n_chars']} 字符）")
    print(c["content"][:200] + "……")
