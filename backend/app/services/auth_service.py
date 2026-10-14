# -*- coding: utf-8 -*-
"""
认证业务：登录、改自己的密码、改自己的资料
==========================================
跟 user_service.py 的分工：**本文件全是"用户操作自己"**，
user_service.py 全是"管理员操作别人"。这个界线要守住 ——
一旦混进去"如果是管理员就跳过旧密码校验"这种分支，后面就再也理不清了。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.common.exceptions import (
    AccountDisabledError,
    AuthError,
    NotFoundError,
)
from backend.app.models.user import STATUS_ACTIVE, User
from backend.app.security.password import hash_password, verify_password
from backend.app.security.token import create_token
from backend.app.services.user_service import user_to_dict
from backend.app.utils.time_fmt import now


def login(db: Session, username: str, password: str) -> dict:
    """校验账号密码，成功则返回 {用户信息..., token}。

    失败时**只给一句话**（"账号或密码不对"），不区分是账号不存在还是密码错：
        区分了就等于告诉攻击者"这个账号是存在的"，
        他可以拿着这份名单去别的网站试同一批密码（撞库）。
        安全类错误消息的原则是：**宁可让用户多打一次客服电话，也不给攻击者任何额外信息。**
    """
    user = db.query(User).filter(User.username == username.strip()).first()

    if user is None or not verify_password(password, user.password_hash):
        raise AuthError("账号或密码不对")

    # 禁用检查放在密码校验**之后**：先确认对方确实是账号主人，再告诉他"你被禁用了"。
    # 顺序反过来的话，任何人输个用户名就能问出"这个账号存在且被禁用"。
    if user.status != STATUS_ACTIVE:
        raise AccountDisabledError("账号已被禁用，请联系管理员")

    user.last_login_at = now()
    db.commit()
    db.refresh(user)

    return {**user_to_dict(user), "token": create_token(user.id, user.username, user.role)}


def change_password(db: Session, user: User, old_password: str, new_password: str) -> None:
    """用户改自己的密码。必须先验证旧密码。"""
    if not verify_password(old_password, user.password_hash):
        raise AuthError("当前密码不对")

    if old_password == new_password:
        raise AuthError("新密码不能和当前密码相同")

    user.password_hash = hash_password(new_password)
    db.commit()


def update_profile(db: Session, user: User, name: str, email: str) -> dict:
    """改自己的名字 / 邮箱。

    注意这里**不允许改 username 和 role** ——
    账号名是登录凭据、role 是权限，让用户自己改等于让用户自己发管理员权限。
    要改这两样只能由管理员在「账号管理」页做。
    """
    if not name or not name.strip():
        raise AuthError("名字不能为空")

    user.name = name.strip()
    user.email = email
    db.commit()
    db.refresh(user)
    return user_to_dict(user)


def load_user(db: Session, user_id: int) -> User:
    """按 id 取用户，取不到就 404。

    单独抽出来是因为"拿不到就报错"这个模式在好几个地方要用，
    每次手写 if user is None 容易漏。
    """
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("用户不存在")
    return user
