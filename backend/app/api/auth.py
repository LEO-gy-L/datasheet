# -*- coding: utf-8 -*-
"""
认证接口
========
    POST /api/auth/login      换 token
    GET  /api/auth/me         拿当前用户（刷新页面时用它恢复登录态）
    POST /api/auth/logout     退出
    PUT  /api/auth/password   改自己的密码
    PUT  /api/auth/profile    改自己的名字 / 邮箱

⚠️ 这个文件里**一处 try/except 都没有**，业务异常全部交给 main.py 里注册的
   全局异常处理器映射状态码。为什么不在每个路由里写 try/except：
    5 个路由文件 × 5 种异常 = 25 段一模一样的样板代码，改一处漏一处。
    集中在一处映射，路由函数就只剩下"调服务 + 返回结果"，一眼看得懂。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.dependencies.auth import get_current_user
from backend.app.models.user import User
from backend.app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    UpdateProfileRequest,
)
from backend.app.services import auth_service
from backend.app.services.user_service import user_to_dict

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)) -> dict:
    """登录。返回 {用户信息..., token}。

    ⚠️ 出参故意不写 response_model（见 schemas/auth.py 文件头说明）：
       返回的字典是 service 组装好的、字段名与前端 mock 完全一致的结构，
       加一层模型只会多一处要同步维护的定义。
    """
    return auth_service.login(db, req.username, req.password)


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    """拿当前登录用户。

    前端 AuthContext 在应用启动时调它，解决"刷新页面后只剩 localStorage 里一份
    可能已经过期的用户信息"的问题 —— 拿 token 问一次后端，token 有效才认。
    顺便还能拿到最新的名字/邮箱（万一管理员改过）。
    """
    return user_to_dict(user)


@router.post("/logout")
def logout() -> dict:
    """退出登录。

    ⚠️ 这个接口**故意不做任何事，也不要求登录**：
       JWT 是无状态的，服务端手里没有"已发出的 token 列表"，所以没有东西可以作废。
       真正的"退出"由前端删掉 localStorage 里的 token 完成。
       留着这个接口是为了两件事：
         ① 前端调用路径统一（所有请求都走后端）
         ② 将来如果加了"token 黑名单"，在这里写进去就行，前端不用改
       也因为它不要求登录，所以 token 已经过期时调它不会报错，前端的退出流程永远走得通。
    """
    return {"ok": True}


@router.put("/password")
def change_password(
    req: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """改自己的密码。必须提供旧密码 —— 这是防止"别人趁你没锁屏改掉你的密码"。"""
    auth_service.change_password(db, user, req.oldPassword, req.newPassword)
    return {"ok": True}


@router.put("/profile")
def update_profile(
    req: UpdateProfileRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """改自己的名字 / 邮箱，返回更新后的用户信息（前端拿去更新顶栏显示）。"""
    return auth_service.update_profile(db, user, req.name, req.email)
