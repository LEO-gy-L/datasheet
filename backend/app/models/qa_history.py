# -*- coding: utf-8 -*-
"""
qa_history 表 —— 问答历史
=========================
一次问答 = 一行。用户在助理页每问一句，后端答完就往这里写一行。

为什么 sources 存成一坨 JSON 文本，而不是单开一张 qa_sources 表：
    它是一份"展示用的标签数组"，比如 ["STM32F103C8_Datasheet.pdf 第 37 页"]。
    从来不会有"反查某个页码被哪些问题引用过"这种需求 ——
    那就意味着它不需要索引、不需要 join、不需要被单独查询。
    单开一张表的唯一后果是每次读历史都要多一次联表查询。**存 JSON 文本是对的。**

conversation_id 现在是空的（NULL），一个字段都没用到 —— 那为什么还留着：
    因为**改字段比加字段贵得多**。现在留一个空列，将来要做"多轮对话"
    （把同一个会话的几问几答串起来）时，只要开始往里写值就行，不用改表结构、
    不用写迁移脚本、不用管历史数据。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base


class QaHistory(Base):
    __tablename__ = "qa_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 归属人。index=True 是因为"查我的历史"永远带着 user_id 过滤，这是最常用的查询条件。
    # ondelete 不写（SQLite 默认不级联）：删用户时历史记录留着，
    # 管理员查历史还能看到"某人问过什么"，这比数据凭空消失好。
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)

    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text, default="")

    # 出处标签数组的 JSON 文本，例如 '["xx.pdf 第 37 页", "yy.pdf 第 2 页"]'
    sources: Mapped[str] = mapped_column(Text, default="[]")

    # 这次提问限定了哪份手册（助理页选中的 PDF）。None = 全部手册里检索。
    source_doc: Mapped[str | None] = mapped_column(String(256), nullable=True)

    seconds: Mapped[float] = mapped_column(Float, default=0.0)

    # 预留：多轮对话的会话 id。现在恒为 None。
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # index=True：历史列表永远按时间倒序取最新 N 条，这个索引直接用得上
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)

    def __repr__(self) -> str:
        return f"<QaHistory id={self.id} user={self.user_id} q={self.question[:20]!r}>"
