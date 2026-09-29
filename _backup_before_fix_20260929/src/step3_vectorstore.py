# -*- coding: utf-8 -*-
"""
第 3 步：把切好的文本块转成向量，存进 FAISS 向量数据库
======================================================
这一步做完后，vectorstore/ 目录里会出现索引文件，
以后每次问答不用重复建库，直接加载就行。

运行方法：
    .venv\\Scripts\\python src\\step3_vectorstore.py

注意：只在"文档有新增/修改"时才需要重跑这一步。
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import ZhipuAIEmbeddings
from langchain_community.vectorstores import FAISS

# ---------- 0. 读密钥 ----------
load_dotenv()
zhipu_key = os.getenv("ZHIPUAI_API_KEY")
if not zhipu_key or "在这里填" in zhipu_key:
    raise SystemExit("请先在 .env 文件里填入你的 ZHIPUAI_API_KEY！")

# ---------- 1. 加载文档（和第 2 步一模一样的逻辑） ----------
BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "datasheets"
STORE_DIR = BASE_DIR / "vectorstore"   # FAISS 索引保存位置

documents = []
for file_path in DATA_DIR.iterdir():
    if file_path.suffix.lower() == ".pdf":
        docs = PyPDFLoader(str(file_path)).load()
    elif file_path.suffix.lower() == ".txt":
        docs = TextLoader(str(file_path), encoding="utf-8").load()
    else:
        continue
    documents.extend(docs)
    print(f"已加载：{file_path.name}")

# ---------- 2. 切块 ----------
splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
chunks = splitter.split_documents(documents)
print(f"共 {len(chunks)} 个文本块，开始向量化（每块都要调一次 embedding）……")

# ---------- 3. 创建 embedding 模型 ----------
# embedding = 把一段文字变成一串数字（向量），意思相近的文字向量也相近
# 智谱的 embedding-3 目前免费，出错的话可以改成 model="embedding-2"
embeddings = ZhipuAIEmbeddings(model="embedding-3")

# ---------- 4. 建 FAISS 向量库 ----------
# 这一步会把每个 chunk 发给智谱换成向量，再存进 FAISS 索引
vectorstore = FAISS.from_documents(chunks, embeddings)

# ---------- 5. 保存到本地 ----------
# 保存后 vectorstore/ 里会出现 index.faiss 和 index.pkl 两个文件
vectorstore.save_local(str(STORE_DIR))
print(f"\n向量库已保存到：{STORE_DIR}")
print("以后问答直接加载它，不用重新向量化（省时间也省 embedding 调用次数）")
