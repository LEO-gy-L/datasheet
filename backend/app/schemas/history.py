# -*- coding: utf-8 -*-
"""
问答历史的数据契约
==================
历史记录只读（除了删除），所以入参只有一个查询条件；没有"创建历史"的入参模型 ——
历史是 /api/ask 答完之后**后端自己写的**，用户不能伪造一条"我问过什么"。
"""
from __future__ import annotations

from pydantic import BaseModel


class HistoryQuery(BaseModel):
    """GET /api/history 的查询参数（实际由接口函数的 query 参数解析，
    这个类留作字段说明的单一出处）。"""

    keyword: str | None = None      # 按问题内容模糊搜
    limit: int = 50                 # 默认一次给 50 条
    offset: int = 0                 # 分页偏移


class HistoryOut(BaseModel):
    """一条历史记录长什么样（字段名与前端 mock 对齐）。

    注意 sources：数据库里存的是 JSON 文本，接口返回时**要解成真正的数组**
    （pydantic 会自动把 list 序列化成 JSON 数组），否则前端拿到的是一串字符串，
    没法 map 成标签。
    """

    id: int
    question: str
    answer: str
    sources: list[str] = []
    sourceDoc: str | None = None
    seconds: float = 0.0
    createdAt: str = ""
