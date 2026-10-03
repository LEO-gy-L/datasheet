# -*- coding: utf-8 -*-
"""把 RAGEngine 包装成一个"可注入的依赖"。

它是一个很薄的转发函数，存在的意义是**让接口层不直接 import 业务实现**：
    api/qa.py 依赖的是 dependencies/engine.py 提供的"一个引擎"
    引擎具体怎么造、是不是单例，由 services/ 决定
这样以后要换检索实现（比如上 CH32F103 的混合检索），接口一行都不用改。
"""
from __future__ import annotations

from backend.app.services.rag_service import RAGEngine, get_engine


def engine_dependency() -> RAGEngine:
    """返回全局唯一的引擎实例。FastAPI 在每次请求前调用它。"""
    return get_engine()
