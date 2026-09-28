# -*- coding: utf-8 -*-
"""
第 2 步：加载 datasheets/ 目录里的文档，并切成小块
====================================================
为什么要切块：数据手册几十上百页，模型一次读不下，
而且用户问"GPIO 电流多少"时只需要相关那一小段，所以先切小，后面才好检索。

运行方法：
    .venv\\Scripts\\python src\\step2_load_split.py
"""

from pathlib import Path
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

# ---------- 1. 找到 datasheets 目录 ----------
# Path(__file__) 是本文件自己；parents[1] 是项目根目录 datasheet-rag
BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "datasheets"

documents = []  # 用来装所有读进来的文档，先建个空列表

# ---------- 2. 逐个文件读取 ----------
for file_path in DATA_DIR.iterdir():
    if file_path.suffix.lower() == ".pdf":
        # PDF 用 PyPDFLoader，每页变成一个 Document 对象
        loader = PyPDFLoader(str(file_path))
        docs = loader.load()
    elif file_path.suffix.lower() == ".txt":
        # TXT 用 TextLoader，整个文件变成一个 Document 对象
        # encoding="utf-8" 防止中文乱码
        loader = TextLoader(str(file_path), encoding="utf-8")
        docs = loader.load()
    else:
        # 其他格式（图片、word 等）暂时跳过
        print(f"跳过不支持的文件：{file_path.name}")
        continue

    documents.extend(docs)  # 把这个文件读出的页追加进总列表
    print(f"已加载：{file_path.name}（{len(docs)} 个 Document）")

print(f"\n共加载 {len(documents)} 个 Document（PDF 一页一个，TXT 一个文件一个）")

# ---------- 3. 切块 ----------
# RecursiveCharacterTextSplitter：按"段落→句子→字"的顺序找自然的切断点
# chunk_size=500：每块大约 500 个字符
# chunk_overlap=50：相邻两块重叠 50 字，防止一句话被从中间砍断
splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=50,
)
chunks = splitter.split_documents(documents)

print(f"切成了 {len(chunks)} 个文本块（chunk）")

# ---------- 4. 打印前 3 块看看效果 ----------
for i, chunk in enumerate(chunks[:3], start=1):
    print("\n" + "=" * 50)
    print(f"第 {i} 块，长度 {len(chunk.page_content)} 字：")
    print(chunk.page_content[:150] + "……")  # 只打印前 150 字预览
