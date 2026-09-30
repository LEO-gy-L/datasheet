# -*- coding: utf-8 -*-
"""
后端 API 服务（FastAPI）
=========================
作用：把 RAG 问答能力包装成一个网址接口，供网页（index.html）调用。
      网页负责好看，这里负责干活——这就是"前后端分离"。

启动方法（在 datasheet 目录下）：
    .venv\\Scripts\\python -m uvicorn src.api:app --host 127.0.0.1 --port 8000

启动后浏览器访问 http://127.0.0.1:8000/docs 能看到自动生成的接口文档。
"""

import sys
from pathlib import Path

# 让本文件以 uvicorn 模块方式启动时，也能 import 到同目录的 rag_engine
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from rag_engine import RAGEngine   # noqa: E402


# ---------- 加载 RAG 引擎（服务启动时只加载一次） ----------
# 如果向量库不存在，rag_engine 会抛 SystemExit，这里转成人话
try:
    engine = RAGEngine()
except SystemExit as e:
    raise RuntimeError(str(e)) from None


# ---------- 创建 FastAPI 应用 ----------
app = FastAPI(title="Datasheet RAG API", version="1.0")

# CORS：只允许本地来源。
# "null" 是为了兼容"双击打开本地 index.html"（file:// 协议的 Origin 是字符串 null）。
# 生产环境要改成你的真实域名，否则任何网站都能调你的接口、花你的 API Key。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["null", "http://localhost:8000", "http://127.0.0.1:8000", "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],

)


# ---------- 定义请求体格式 ----------
class AskRequest(BaseModel):
    """POST /api/ask 收到的 JSON：{"question": "...", "source": "可选"}"""
    # max_length=2000：防止有人把整本手册粘进来，一次请求烧掉几十万 token
    question: str = Field(..., min_length=1, max_length=2000)
    source: str | None = None   # 想只看某份手册时传，例如 "STM32F103C8_Datasheet.pdf"


# ---------- 接口：健康检查（网页用它判断后端有没有启动） ----------
@app.get("/api/health")
def health():
    return {"status": "ok"}


# ---------- 接口：提问（核心） ----------
@app.post("/api/ask")
def ask(req: AskRequest):
    try:
        res = engine.ask(req.question, source=req.source)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        # 模型调用失败（网络/余额/限流）-> 503，前端能显示可读原因
        raise HTTPException(status_code=503, detail=str(e)) from e

    return {
        "answer": res["answer"],
        "sources": res["sources"],
        "seconds": res["seconds"],
    }
