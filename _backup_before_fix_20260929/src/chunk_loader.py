# -*- coding: utf-8 -*-
"""
P1 第 1 步：把清洗后的 Markdown 产物切成小块
==============================================

输入：
    data/text_v2/<pdf_stem>/page_*.md   正文页
    data/tables_v5/<pdf_stem>/page_*.md 表格页

输出：
    data/chunks_v2/<pdf_stem>/chunks.jsonl

规则：
    - 表格整张保留（前面解析的成果，不能切碎）
    - 正文按 400 字符切，重叠 50 字符
    - 元数据 [来源]/[页码]/[标题]/[类型] 从 content 里剥离，只保留在 JSON 字段里
"""

import json
import re
from pathlib import Path


# ---------- 配置 ----------
TEXT_MAX_CHARS = 400
TEXT_OVERLAP_CHARS = 50

DOC_RE = re.compile(
    r"\[来源\] (.*?)\n\[页码\] (\d+)\n\[标题\] (.*?)\n\[类型\] (text|table)\n\n(.*)",
    re.S,
)


def split_text(content: str, page_no: int, source: str, title: str,
               chunk_id_prefix: str) -> list[dict]:
    """把一页正文切成多块。"""
    chunks: list[dict] = []
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    if not paragraphs:
        return chunks

    buf = ""
    for para in paragraphs:
        if len(buf) + len(para) > TEXT_MAX_CHARS and buf:
            chunks.append({
                "id": f"{chunk_id_prefix}-{len(chunks):04d}",
                "type": "text",
                "source": source,
                "page": page_no,
                "title": title,
                "content": buf.strip(),
                "n_chars": len(buf.strip()),
            })
            buf = buf[-TEXT_OVERLAP_CHARS:] if len(buf) > TEXT_OVERLAP_CHARS else ""
        buf += ("\n\n" + para) if buf else para

    if buf.strip():
        chunks.append({
            "id": f"{chunk_id_prefix}-{len(chunks):04d}",
            "type": "text",
            "source": source,
            "page": page_no,
            "title": title,
            "content": buf.strip(),
            "n_chars": len(buf.strip()),
        })

    return chunks


def load_documents(text_dir: Path, table_dir: Path) -> list[dict]:
    """从 text_dir 和 table_dir 加载所有文档块。"""
    docs: list[dict] = []

    # 正文
    if text_dir.exists():
        for md_file in sorted(text_dir.glob("page_*.md")):
            raw = md_file.read_text(encoding="utf-8")
            m = DOC_RE.fullmatch(raw.strip())
            if not m:
                continue
            source, page_no, title, doc_type, content = m.groups()
            page_no = int(page_no)
            prefix = f"text-p{page_no:03d}"
            docs.extend(split_text(content.strip(), page_no, source.strip(),
                                   title.strip(), prefix))

    # 表格：一页可能有多张表，都要解析
    if table_dir.exists():
        for md_file in sorted(table_dir.glob("page_*.md")):
            raw = md_file.read_text(encoding="utf-8").strip()
            for m in DOC_RE.finditer(raw):
                source, page_no, title, doc_type, content = m.groups()
                page_no = int(page_no)
                body = content.strip()
                if not body:
                    continue
                docs.append({
                    "id": f"table-p{page_no:03d}-{len(docs):04d}",
                    "type": "table",
                    "source": source.strip(),
                    "page": page_no,
                    "title": title.strip(),
                    "content": body,
                    "n_chars": len(body),
                })

    return docs


def main() -> None:
    PDF_NAME = "STM32F103C8_Datasheet"
    TEXT_DIR = Path("data/text_v2") / PDF_NAME
    TABLE_DIR = Path("data/tables_v5") / PDF_NAME
    OUT_DIR = Path("data/chunks_v2") / PDF_NAME
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    chunks = load_documents(TEXT_DIR, TABLE_DIR)

    jsonl_path = OUT_DIR / "chunks.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    n_text = sum(1 for c in chunks if c["type"] == "text")
    n_table = sum(1 for c in chunks if c["type"] == "table")

    print(f"共生成 {len(chunks)} 块")
    print(f"  正文块：{n_text} 块")
    print(f"  表格块：{n_table} 块")
    print(f"  输出：{jsonl_path}")

    # 示例
    if chunks:
        c = chunks[0]
        print("\n" + "=" * 50)
        print(f"[{c['type']}] {c['title']}（页 {c['page']}，{c['n_chars']} 字符）")
        print(c["content"][:200] + "……")


if __name__ == "__main__":
    main()
