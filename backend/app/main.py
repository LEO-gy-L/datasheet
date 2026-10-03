# -*- coding: utf-8 -*-
"""
FastAPI 应用装配（后端启动点）
==============================
这是**整个后端的入口**。它只做"装配"，不写任何业务逻辑：

    创建 app  ->  挂 CORS 中间件  ->  注册路由  ->  启动时预热引擎

启动方法（**必须在项目根目录**，模块路径是相对当前目录解析的）：

    python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
或者直接双击项目根目录的 start_backend.bat（里面就是上面这一行）。

启动后浏览器访问：
    http://127.0.0.1:8000/docs    自动生成的接口文档，可以直接点 "Try it out" 提问
    http://127.0.0.1:8000/api/health   健康检查，网页用它判断后端有没有起来

⚠️ 访问根路径 http://127.0.0.1:8000/ 会返回 404 —— 这是正常的：
   没有定义 "/" 这个路由。这不是故障，是"这里本来就没东西"。
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api import qa
from backend.app.config import API_TITLE, API_VERSION, CORS_ORIGINS
from backend.app.services.rag_service import get_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    """服务生命周期钩子。

    yield 之前 = 开始接收请求之前：这里预热引擎（加载 FAISS 索引 + 初始化模型）。

    为什么要放在这里，而不是等第一个请求来了再加载：
        **快速失败**。向量库不存在的话，启动阶段就直接报错退出，
        你能立刻看到红字；否则要等你问了第一个问题，才收到一句
        "没找到向量库"，还得去翻日志才知道是启动时的问题。

    yield 之后 = 服务关闭时。目前没有需要清理的资源（FAISS 是只读内存映射），
    以后接了数据库连接池、后台任务，清理逻辑写在这里。
    """
    get_engine()
    yield


app = FastAPI(title=API_TITLE, version=API_VERSION, lifespan=lifespan)

# CORS（跨源资源共享）：
#   浏览器有个安全规则 —— 网页只能请求"同源"的接口。
#   前端跑在 5173、后端跑在 8000，端口不同就算跨源，不配这个白名单，
#   浏览器会直接拦掉请求并报 "blocked by CORS policy"（后端其实收到了，是浏览器不给看）。
# 白名单具体内容在 config.CORS_ORIGINS 里。
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# 把路由挂上来。qa.router 自带 "/api" 前缀，所以两个接口是
#   GET  /api/health
#   POST /api/ask
# 以后加 documents.py / history.py，各自再来一行 include_router 即可。
app.include_router(qa.router)
