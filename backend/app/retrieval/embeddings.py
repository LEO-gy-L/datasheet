# -*- coding: utf-8 -*-
"""
向量化模型（智谱 embedding-3）
=============================
入库（ingestion/indexer.py）和检索（services/rag_service.py）用的是**同一个模型**，
所以放在这里让两边共用 —— 这也是"检索层"独立成一个包的第一个理由。

⚠️ 唯一铁律：EMBED_MODEL 必须和建库时用的完全一致。
   嵌入模型决定"向量空间"的坐标系。换了模型，旧向量还在旧坐标系里，
   新问题在新坐标系里 —— 距离全是错的，检索结果整体错乱。
   **最坑的是它不报错**，只是答得离谱，很难查。
   所以一旦换模型，必须重建向量库：python -m backend.app.ingestion.indexer
"""
from __future__ import annotations

from functools import lru_cache

from langchain_community.embeddings import ZhipuAIEmbeddings

from backend.app.config import EMBED_MODEL


@lru_cache(maxsize=1)
def get_embeddings() -> ZhipuAIEmbeddings:
    """返回全局唯一的 embeddings 实例。

    @lru_cache(maxsize=1) 是标准库的缓存装饰器：
        LRU = Least Recently Used（最近最少使用），maxsize=1 表示只留一份。
        第一次调用真正创建对象，之后每次调用直接返回同一个 ——
        避免"每次提问都重新初始化一次模型"。

    想清空缓存（测试时会用到）：get_embeddings.cache_clear()
    """
    return ZhipuAIEmbeddings(model=EMBED_MODEL)
