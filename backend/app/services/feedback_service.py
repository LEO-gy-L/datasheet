# -*- coding: utf-8 -*-
"""
反馈业务
========
闭环：用户在助理页提交 → 管理员在后台看到 → 回复 → 用户在自己那页看到回复。

⚠️ 返回结构里为什么要带 username：
    前端反馈表格有一列"提交人"（显示的是账号名，不是 id）。
    而 feedbacks 表里存的是 user_id。所以查询时必须 join 一次 users 表把账号名取出来 ——
    否则前端拿到一串数字，页面上就会显示 "1"、"2" 而不是 "zhang"、"li"。

⚠️ 这个文件里最要紧的一句话是：**不要相信前端传来的身份信息**。
    前端提交反馈时会带上 username 字段（mock 时代留下的习惯），
    但服务端一律从 token 里取当前用户 id 写入 —— 否则任何人都能伪造一条
    "用户 x 提的反馈"。前端多传的字段 pydantic 会自动忽略，不用管它。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.common.exceptions import ForbiddenError, NotFoundError
from backend.app.models.feedback import (
    STATUS_PENDING,
    STATUS_RESOLVED,
    Feedback,
)
from backend.app.models.user import ROLE_ADMIN, User
from backend.app.utils.time_fmt import fmt, now


def create(db: Session, user: User, payload: dict) -> dict:
    """用户提交一条反馈。

    category 的合法性**不在这里校验** —— 它是"用户能不能选到这个值"的问题，
    前端下拉框已经限制了。后端如果硬要白名单校验，以后加一个分类就要改两处，
    而现在即使有脏分类进来，最坏后果也只是后台多一个看不懂的分类标签，不值得为它加代码。
    """
    row = Feedback(
        user_id=user.id,
        category=payload.get("category", ""),
        content=payload.get("content", ""),
        question=payload.get("question", ""),
        answer=payload.get("answer", ""),
        status=STATUS_PENDING,
        created_at=now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_dict(row, user.username)


def list_for(db: Session, user: User, status: str | None = None) -> list[dict]:
    """反馈列表。

    权限分叉点就在这一行：**管理员看全部，普通用户只看自己的**。
    这是本文件里唯一涉及"谁能看什么"的地方，改它之前先想清楚。
    """
    # 一次查询同时取出反馈和提交人账号名（避免 N+1：不是每条反馈再查一次用户表）
    q = db.query(Feedback, User.username).join(User, Feedback.user_id == User.id)

    if user.role != ROLE_ADMIN:
        q = q.filter(Feedback.user_id == user.id)
    if status:
        q = q.filter(Feedback.status == status)

    # 新的排前面。同样加 id 作二级排序，避免同秒创建的记录顺序抖动。
    rows = q.order_by(Feedback.created_at.desc(), Feedback.id.desc()).all()
    return [_to_dict(fb, username) for fb, username in rows]


def update(db: Session, admin: User, feedback_id: int, status: str | None, reply: str | None) -> dict:
    """管理员回复 / 改状态。"""
    if admin.role != ROLE_ADMIN:
        raise ForbiddenError("需要管理员权限")

    row = db.get(Feedback, feedback_id)
    if row is None:
        raise NotFoundError("反馈不存在")

    if status:
        row.status = status

    if reply is not None:
        row.reply = reply
        row.replied_by = admin.id
        # 回复时间只在**真正有回复内容**时写。
        # 为什么加这个条件：管理员可能只把状态从"待处理"点成"处理中"、回复框还空着，
        # 这种情况不该留下"已回复时间" —— 否则用户那边会看到"已回复"但内容是空的。
        if reply.strip():
            row.replied_at = now()

    db.commit()
    db.refresh(row)

    # 重新取一次提交人账号名（admin 可能是别人，不能用当前登录者的名字糊弄）
    username = db.get(User, row.user_id)
    return _to_dict(row, username.username if username else "未知")


def _to_dict(row: Feedback, username: str) -> dict:
    """ORM -> 前端字典。字段名与 mock/data.js 的 FEEDBACKS 完全一致。"""
    return {
        "id": row.id,
        "username": username,
        "category": row.category,
        "question": row.question,
        "answer": row.answer,
        "content": row.content,
        "status": row.status,
        "reply": row.reply,
        "createdAt": fmt(row.created_at),
        "repliedAt": fmt(row.replied_at),
    }
