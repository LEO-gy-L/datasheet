# -*- coding: utf-8 -*-
"""
反馈接口的数据契约
==================
前端提交的字段（见 views/user/Assistant.jsx 的 submitFeedback）：
    username / category / content / question / answer

⚠️ 前端传的是 **username**（不是 user_id），因为 mock 时代前端手里只有用户名。
   接后端后 username 由服务端从 token 里取，**不信任前端传的 username** ——
   否则用户 A 可以伪造一条"用户 B 提的反馈"。
   所以下面这个模型里故意**没有** username 字段：多余字段 pydantic 默认忽略，
   前端照旧传它的，后端不用就是了。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FeedbackCreate(BaseModel):
    """POST /api/feedbacks —— 用户提交反馈。"""

    category: str = Field(..., min_length=1, max_length=32)
    content: str = Field(..., min_length=1, max_length=2000)

    # 被反馈的那一轮问答。允许为空：将来可能支持"直接进反馈页提建议"，
    # 那种反馈没有具体针对的回答。
    question: str = Field("", max_length=2000)
    answer: str = Field("", max_length=8000)


class FeedbackUpdate(BaseModel):
    """PUT /api/feedbacks/{id} —— 管理员回复 / 改状态。

    两个字段都可选：管理员可能只改状态（比如先把待处理点成处理中），
    也可能一次把回复和状态一起提交（前端现在是后者）。
    """
    status: Literal["pending", "processing", "resolved"] | None = None
    reply: str | None = Field(None, max_length=2000)
