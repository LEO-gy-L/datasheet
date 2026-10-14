# -*- coding: utf-8 -*-
"""
用户管理接口（管理员专用）
==========================
    GET  /api/users                  列表 + 模糊搜索
    PUT  /api/users/{id}             改账号名 / 名字 / 邮箱
    PUT  /api/users/{id}/password    重置密码（就是"忘记密码"那条通道）
    PUT  /api/users/{id}/status      启用 / 禁用

⚠️ 整个文件都挂在 require_admin 上 —— 普通用户调这些接口会拿到 403。
   权限要求写在这里（接口层），而不是散在 service 里，原因是
   "这个 URL 谁能访问"是接口层的知识，service 只管业务规则。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.dependencies.auth import require_admin
from backend.app.models.user import User
from backend.app.schemas.user import PasswordReset, StatusPatch, UserPatch
from backend.app.services import user_service

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("")
def list_users(
    keyword: str | None = Query(None, description="按账号 / 名字 / 邮箱模糊搜"),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    """用户列表。

    ⚠️ 路径写 "" 而不是 "/"：
       FastAPI 里 prefix="/api/users" + path="" 的完整路径是 `/api/users`
       （没有结尾斜杠，跟前端 api/users.js 里写的 `request("/users?...")` 完全对上）。
       写成 "/" 的话路径会变成 `/api/users/`，FastAPI 默认会额外发一个 307 重定向 ——
       前端 fetch 跟着跳过去虽然也能通，但每次多一次请求，日志里也难看。

    参数名 _admin 前面加下划线：表示"我需要在依赖里做权限校验，但函数体用不到它"。
    Python 里没有真正的"只写参数不用"的语法，下划线开头是社区通用约定。
    """
    return user_service.list_users(db, keyword)


@router.put("/{user_id}")
def update_user(
    user_id: int,
    patch: UserPatch,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """改资料。

    ⚠️ 这里用 `patch.model_dump(exclude_unset=True)` 而不是 `patch.model_dump()`：
       前者只包含**前端真的传了的字段**，后者会把没传的字段补成 None。
       后果差别很大 —— 前端只改名字时，exclude_unset 得到 {"name": "小王"}（邮箱不动）；
       而全量 dump 得到 {"username": None, "name": "小王", "email": None}，
       service 里看到 None 以为是"不改"，虽然结果碰巧一样，
       但一旦以后某个字段允许显式传 None（表示清空），两者就会分道扬镳。
       **要表达"没传"和"传了 null"的区别，必须用 exclude_unset。**
    """
    return user_service.update_user(db, user_id, patch.model_dump(exclude_unset=True))


@router.put("/{user_id}/password")
def reset_password(
    user_id: int,
    req: PasswordReset,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """管理员重置密码。用户忘了密码时由管理员设一个新的，用户登录后再自己改。"""
    user_service.reset_password(db, user_id, req.password)
    return {"ok": True}


@router.put("/{user_id}/status")
def set_status(
    user_id: int,
    req: StatusPatch,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """启用 / 禁用账号。注意这里需要 admin 本人（service 要判断"不能禁用自己"）。"""
    return user_service.set_status(db, admin, user_id, req.status)
