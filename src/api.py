# -*- coding: utf-8 -*-
"""
后端 API 服务（FastAPI）
=========================
作用：把 RAG 问答能力包装成一个网址接口，供网页（web/index.html）调用。
      网页负责好看，这里负责干活——这就是"前后端分离"。

启动方法（在 datasheet-rag 目录下）：
    .venv\\Scripts\\python -m uvicorn src.api:app --host 127.0.0.1 --port 8000

启动后浏览器访问 http://127.0.0.1:8000/docs 能看到自动生成的接口文档。
"""

import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_community.embeddings import ZhipuAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_deepseek import ChatDeepSeek

# ---------- 1. 路径与配置 ----------
BASE_DIR = Path(__file__).resolve().parents[1]
STORE_DIR = BASE_DIR / "vectorstore"
load_dotenv(BASE_DIR / ".env")

# ---------- 2. 加载向量库和模型（服务启动时只加载一次） ----------
if not (STORE_DIR / "index.faiss").exists():
    raise SystemExit("没找到向量库，请先运行：.venv\\Scripts\\python src\\step3_vectorstore.py")

embeddings = ZhipuAIEmbeddings(model="embedding-3")
vectorstore = FAISS.load_local(
    str(STORE_DIR),
    embeddings,
    allow_dangerous_deserialization=True,
)
model = ChatDeepSeek(model="deepseek-chat", temperature=0)

# ---------- 3. 创建 FastAPI 应用 ----------
app = FastAPI(title="Datasheet RAG API", version="1.0")

# CORS：允许网页从别的地址（比如你双击打开的 html 文件）调用这个接口
# 没有这段，浏览器会因为"跨域"直接拦截请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # 允许任何来源，本地开发够用
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- 4. 定义请求体格式 ----------
class AskRequest(BaseModel):
    """POST /api/ask 收到的 JSON 长这样：{"question": "GPIO 电流多少"}"""
    question: str


# ---------- 5. 接口：健康检查（网页用它判断后端有没有启动） ----------
@app.get("/api/health")
def health():
    return {"status": "ok"}


# ---------- 6. 接口：提问（核心） ----------
@app.post("/api/ask")
def ask(req: AskRequest):
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    start = time.time()

    # (1) 检索最相关的 4 块原文
    chunks = vectorstore.similarity_search(question, k=4)
    context = "\n\n".join(c.page_content for c in chunks)

    # (2) 拼 prompt，要求只根据资料回答
    prompt = f"""你是一个芯片数据手册问答助手。请只根据下面提供的资料回答问题。
如果资料里没有答案，就直接说"数据手册中没有提到"，不要自己编。

【资料】
{context}

【问题】
{question}

【回答】"""

    # (3) 调模型
    response = model.invoke(prompt)

    # (4) 整理出处（去重）。
    #     带上页码，前端才能显示"这条答案来自第几页"。
    #     用 list 而不是 set：set 的迭代顺序每次都不一样，
    #     同一个问题问两次、来源顺序会跳来跳去。
    sources = []
    for c in chunks:
        name = Path(c.metadata.get("source", "未知")).name
        ps = c.metadata.get("page_start")
        pe = c.metadata.get("page_end")
        if ps and pe and pe != ps:
            label = f"{name} 第 {ps}-{pe} 页"
        elif ps:
            label = f"{name} 第 {ps} 页"
        else:
            label = name
        if label not in sources:
            sources.append(label)

    return {
        "answer": response.content,
        "sources": sources,
        "seconds": round(time.time() - start, 2),
    }
