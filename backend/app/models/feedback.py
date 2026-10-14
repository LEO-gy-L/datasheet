# -*- coding: utf-8 -*-
"""
feedbacks 表 —— 用户反馈
========================
来源是助理页每条 AI 回答下面那个「反馈」按钮。点开弹窗时，
"这一轮的提问"和"系统当时给的回答"会自动带过来 —— 用户只需要选个分类、写一句说明。

为什么要把 question / answer 一起存下来（而不是只存一个 history_id 指回去）：
    因为"这条反馈针对的是哪一轮回答"是**证据**，不是引用关系。
    用户后来可能把那条历史删了，但反馈里的证据必须留得住 ——
    否则管理员打开反馈只看到一句"回答不准"，完全不知道在说哪条回答，没法处理。

status 三态与前端 mock 完全一致，所以页面代码一行都不用改：
    pending     刚提交，管理员还没看
    processing  管理员已读、正在处理
    resolved    已处理完，会带一条 reply（管理员回复）
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base

STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_RESOLVED = "resolved"

# 允许的分类。写在后端而不是只放前端：
# 前端下拉框是"方便用户选"，后端这份是"防止有人绕过界面塞脏数据"。
# 两处要保持同步（前端那份在 api/feedback.js 的 FEEDBACK_CATEGORIES）。
CATEGORIES = ["答案不准", "检索不到", "格式错乱", "回答太慢", "其他"]


class Feedback(Base):
    __tablename__ = "feedbacks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)

    category: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text, default="")

    # 证据：被反馈的那一轮问答
    question: Mapped[str] = mapped_column(Text, default="")
    answer: Mapped[str] = mapped_column(Text, default="")

    status: Mapped[str] = mapped_column(String(16), default=STATUS_PENDING, index=True)
    reply: Mapped[str] = mapped_column(Text, default="")

    # 谁回复的。可空：还没回复时就是 None。
    replied_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<Feedback id={self.id} user={self.user_id} status={self.status}>"
