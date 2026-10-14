# -*- coding: utf-8 -*-
"""
反馈接口
========
    GET  /api/feedbacks?status=     列表（普通用户只看自己的，管理员看全部）
    POST /api/feedbacks             提交（用户）
    PUT  /api/feedbacks/{id}        回复 / 改状态（管理员）

⚠️ "管理员看全部、用户看自己"这个分叉**不在接口层 diff 路径**，
   而是在 service 里按 role 决定 where 条件（见 feedback_service.list_for）。
   为什么不做成两个接口（/my-feedbacks 和 /feedbacks）：
     因为前端只有一份表格组件，两个接口意味着两套调用逻辑、
     而且要判断"当前角色该调哪个"。一个接口内部按角色收敛，前端永远只调一个。
     代价是"这个接口的行为取决于调用者角色" —— 必须在注释里写清楚（就是这段）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.dependencies.auth import get_current_user, require_admin
from backend.app.models.user import User
from backend.app.schemas.feedback import FeedbackCreate, FeedbackUpdate
from backend.app.services import feedback_service

router = APIRouter(prefix="/api/feedbacks", tags=["feedbacks"])


@router.get("")
def list_feedbacks(
    status: str | None = Query(None, description="pending / processing / resolved"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    """反馈列表。注意依赖是 get_current_user（不是 require_admin）——
    普通用户要能进来看到**自己**提交的那些和它们的回复。"""
    return feedback_service.list_for(db, user, status)


@router.post("")
def create_feedback(
    req: FeedbackCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """提交反馈。

    ⚠️ 提交人取自 `user`（token 里解析出来的），**不是前端传的 username**。
       前端确实会多传一个 username 字段（mock 时代留下的），pydantic 会忽略它。
       如果这里信了前端传的值，任何人都能伪造一条"别人提的反馈"。
    """
    return feedback_service.create(db, user, req.model_dump())


@router.put("/{feedback_id}")
def update_feedback(
    feedback_id: int,
    req: FeedbackUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """管理员回复 / 改状态。

    用 exclude_unset 区分"没传 status"和"传了 status=null" ——
    这里字段本来就可选，所以两者都表示"不改"，但保持跟 users.py 一致的写法，
    免得以后有人加字段时想岔。
    """
    data = req.model_dump(exclude_unset=True)
    return feedback_service.update(db, admin, feedback_id, data.get("status"), data.get("reply"))
