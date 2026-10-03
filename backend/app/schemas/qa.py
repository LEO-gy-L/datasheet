# -*- coding: utf-8 -*-
"""
问答接口的数据契约
==================
⚠️ AskResponse 的字段名必须与前端 frontend/ 里的取值一一对应，改动要前后端同时改。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    """POST /api/ask 的请求体：{"question": "...", "source": "可选"}"""

    # max_length=2000 是成本保护：防止有人把整本手册粘进来，
    # 一次请求就烧掉几十万 token。
    question: str = Field(..., min_length=1, max_length=2000, description="用户问题")

    # 想只看某份手册时传文件名，例如 "STM32F103C8_Datasheet.pdf"
    source: str | None = Field(None, description="限定检索的单份手册文件名")


class AskResponse(BaseModel):
    """POST /api/ask 的响应体。

    这里**没有 chunks 字段**是刻意的：
    RAGEngine.ask() 会返回命中的原始 Document 列表（评测脚本要它的页码），
    但那是内部结构，不该出现在 HTTP 响应里 —— 体积大、也没必要暴露。
    response_model 会自动把多余的键过滤掉。
    """

    answer: str = Field(..., description="模型回答")
    sources: list[str] = Field(default_factory=list, description="答案来源标签（含页码）")
    seconds: float = Field(..., description="本次问答耗时（秒）")
