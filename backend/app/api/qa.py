# -*- coding: utf-8 -*-
"""
问答接口
========
    GET  /api/health   健康检查 —— 网页用它判断后端有没有起来
    POST /api/ask      提问（核心接口）

路由写法里的两个要点：

  1. `prefix="/api"` 定义在 APIRouter 上，所以下面写 "/health" 就等于 "/api/health"。
     main.py 里 include_router 时不用再写前缀。

  2. `Depends(engine_dependency)` 是 FastAPI 的"依赖注入"：
     请求进来时，FastAPI 先调用 engine_dependency 拿到引擎，再当作参数传进来。
     好处是这个函数的签名就明确写出了"我需要什么"，而不用自己 import 一个全局变量 ——
     以后想换成 mock 引擎做测试，只换依赖就行，接口代码不动。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.app.common.exceptions import (
    EmptyQuestionError,
    IndexNotFoundError,
    ModelCallError,
)
from backend.app.dependencies.engine import engine_dependency
from backend.app.schemas.qa import AskRequest, AskResponse
from backend.app.services.rag_service import RAGEngine

router = APIRouter(prefix="/api", tags=["qa"])


@router.get("/health")
def health() -> dict:
    """健康检查。

    注意它**不碰向量库、不碰模型** —— 所以永远是毫秒级返回。
    这是故意的：健康检查要能区分"服务活着但依赖挂了"，
    如果把依赖检查塞进来，依赖一挂整个服务就会被误判为已死。
    """
    return {"status": "ok"}


@router.post("/ask", response_model=AskResponse)
def ask(req: AskRequest,
        engine: RAGEngine = Depends(engine_dependency)) -> dict:
    """提问。

    异常 -> HTTP 状态码的映射**全部集中在这里**，
    service 层抛的是业务异常，它完全不知道 HTTP 是什么东西。
    这样同一套 service 能被命令行、Streamlit、网页复用。
    """
    try:
        res = engine.ask(req.question, source=req.source)
    except EmptyQuestionError as e:
        # 400：用户输入有问题，改了再来
        raise HTTPException(status_code=400, detail=str(e)) from e
    except IndexNotFoundError as e:
        # 500：服务端自己没准备好（向量库没建），不是用户的问题
        raise HTTPException(status_code=500, detail=str(e)) from e
    except ModelCallError as e:
        # 503：上游暂时不可用，稍后重试可能就好了
        raise HTTPException(status_code=503, detail=str(e)) from e

    # 只挑前端要用的三个字段返回（response_model 也会再过滤一遍）
    return {
        "answer": res["answer"],
        "sources": res["sources"],
        "seconds": res["seconds"],
    }
