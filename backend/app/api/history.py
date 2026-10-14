# -*- coding: utf-8 -*-
"""
问答历史接口
============
    GET    /api/history?keyword=&limit=&offset=   我的历史（倒序）
    DELETE /api/history/{id}                      删一条
    DELETE /api/history                           清空我的全部

⚠️ 这个文件里**没有任何"user_id"参数** —— 用户是谁完全由 token 决定。
   这是刻意的设计：一旦接口上出现 userId 参数，就意味着"用户可以指定查谁的历史"，
   那就必须在函数体里再加一句"只能查自己"，忘了写就是越权漏洞。
   **让越权在接口签名上就不可能发生**，比指望每次记得写检查可靠得多。

   历史是**写**在 /api/ask 里的（答完顺手记一笔），所以这里没有 POST。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.dependencies.auth import get_current_user
from backend.app.models.user import User
from backend.app.services import history_service

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("")
def list_history(
    keyword: str | None = Query(None, description="按问题内容模糊搜"),
    limit: int = Query(50, ge=1, le=200, description="一次取多少条"),
    offset: int = Query(0, ge=0, description="跳过多少条（分页用）"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    """我的历史列表。

    ge / le 是 pydantic 的数值约束（greater-or-equal / less-or-equal），
    在**接口层**就把 limit=99999 这种请求挡掉，返回 422。
    service 里其实也有一层 clamp（双保险），但让非法请求在门口就被拒绝，
    错误信息更清楚，也不会白跑一次数据库。
    """
    return history_service.list_mine(db, user.id, keyword, limit, offset)


@router.delete("/{history_id}")
def delete_history(
    history_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """删一条。service 里会把 user_id 一起作为查询条件 —— 只能删自己的。"""
    history_service.delete_one(db, user.id, history_id)
    return {"ok": True}


@router.delete("")
def clear_history(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """清空我的全部历史。返回删掉的条数，前端提示"已清空 N 条"。"""
    count = history_service.clear_mine(db, user.id)
    return {"ok": True, "count": count}
