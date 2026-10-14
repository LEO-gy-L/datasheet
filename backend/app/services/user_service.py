# -*- coding: utf-8 -*-
"""
用户管理业务 + 用户对象的"对外模样"
==================================
这个文件里有两个东西：

  1. `user_to_dict()` —— 把 ORM 对象转成"能给前端看的字典"。
     它存在的唯一理由是**安全**：User 对象里有 password_hash 字段，
     直接把对象丢给 FastAPI 序列化，哈希值就会出现在响应体里。
     哈希虽然算不回去，但泄漏它等于送给攻击者一份可以离线暴力破解的素材。
     **所有返回用户信息的地方都必须走这个函数**，绝不直接返回 User 对象。

  2. 管理员操作用户的服务函数（列表 / 改资料 / 重置密码 / 启用禁用）。

⚠️ 这里**不包含登录**：登录在 auth_service.py。区别是"操作的谁" ——
   本文件全是管理员操作**别人**，auth_service 全是用户操作**自己**。
"""
from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app.common.exceptions import ConflictError, NotFoundError
from backend.app.models.user import ROLE_ADMIN, STATUS_ACTIVE, STATUS_DISABLED, User
from backend.app.security.password import hash_password
from backend.app.utils.time_fmt import fmt, now


def user_to_dict(user: User) -> dict:
    """用户对象 -> 前端字典。

    字段名刻意跟前端 mock/data.js 里的 USERS 保持一致（createdAt / lastLogin 是驼峰），
    这样 views/admin/Users.jsx 那套表格代码一行都不用改。

    ⚠️ 这里**永远不能出现 password_hash** —— 加字段前先想清楚它能不能给外人看。
    """
    return {
        "id": user.id,
        "username": user.username,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "status": user.status,
        # 时间统一走 time_fmt，格式是 "2026-10-03 15:20"（前端直接显示，不再二次格式化）
        "createdAt": fmt(user.created_at),
        "lastLogin": fmt(user.last_login_at),
    }


def list_users(db: Session, keyword: str | None = None) -> list[dict]:
    """用户列表。keyword 会在 账号 / 名字 / 邮箱 三个字段里做模糊匹配。

    为什么用 ilike 而不是 like：
        SQLite 的 LIKE 对 ASCII 本来就不区分大小写，但对中文没影响；
        用 ilike 是习惯写法，换到 PostgreSQL 时行为才一致（PG 的 LIKE 区分大小写）。
        % 是 SQL 的通配符，前后都加 = "包含"。
    """
    q = db.query(User)
    if keyword and keyword.strip():
        k = f"%{keyword.strip()}%"
        q = q.filter(or_(User.username.ilike(k), User.name.ilike(k), User.email.ilike(k)))

    # 排序用 id 而不是 created_at：种子账号是同一秒建出来的，
    # 时间相同的话排序结果不稳定（每次刷新顺序可能变），id 单调递增，排序恒稳。
    return [user_to_dict(u) for u in q.order_by(User.id).all()]


def update_user(db: Session, user_id: int, patch: dict) -> dict:
    """改账号名 / 名字 / 邮箱。patch 里为 None 的字段表示"不改"。"""
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("用户不存在")

    # 改账号名要检查唯一性 —— 数据库虽然有 unique 约束会挡住，
    # 但那是 IntegrityError（500 级别的报错），用户看到的会是一句莫名其妙的
    # "服务器内部错误"。先查一次，给一句人能看懂的话。
    new_username = patch.get("username")
    if new_username and new_username != user.username:
        exists = db.query(User).filter(User.username == new_username).first()
        if exists:
            raise ConflictError(f"账号名 {new_username} 已被占用")
        user.username = new_username

    if patch.get("name") is not None:
        user.name = patch["name"]
    if patch.get("email") is not None:
        user.email = patch["email"]

    db.commit()
    db.refresh(user)     # 从库里读回最新值（尤其是数据库生成的字段）
    return user_to_dict(user)


def reset_password(db: Session, user_id: int, new_password: str) -> None:
    """管理员重置密码。不需要旧密码 —— 用户忘了密码才会来找管理员。"""
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("用户不存在")
    user.password_hash = hash_password(new_password)
    db.commit()


def set_status(db: Session, admin: User, user_id: int, status: str) -> dict:
    """启用 / 禁用账号。

    ⚠️ 两条自我保护的规则，看着多余但都是真踩过的坑：
      ① 不能禁用自己 —— 点了之后自己立刻被踢出去，还得去改数据库才能救回来
      ② 不能把最后一个管理员禁用掉 —— 否则整个系统再也没人能进后台
    """
    if status not in (STATUS_ACTIVE, STATUS_DISABLED):
        raise NotFoundError(f"未知状态：{status}")

    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("用户不存在")

    if user.id == admin.id and status == STATUS_DISABLED:
        raise ConflictError("不能禁用当前登录的账号")

    if (
        user.role == ROLE_ADMIN
        and status == STATUS_DISABLED
        and _active_admin_count(db) <= 1
    ):
        raise ConflictError("系统里至少要有 1 个可用的管理员账号")

    user.status = status
    db.commit()
    db.refresh(user)
    return user_to_dict(user)


def _active_admin_count(db: Session) -> int:
    """还有几个能用的管理员 —— 用来判断是不是"最后一个"。"""
    return (
        db.query(User)
        .filter(User.role == ROLE_ADMIN, User.status == STATUS_ACTIVE)
        .count()
    )


def seed_admin(db: Session) -> None:
    """首次启动时建一个默认管理员。已经存在同名账号就什么都不做（幂等）。

    为什么需要它：数据库建好之后是空的，没有这个函数就**谁也进不去系统** ——
    而没有账号的地方是没法"在系统里创建一个账号"的，鸡生蛋问题。
    所以默认管理员必须由程序自己创建（这跟 Linux 的 root、MySQL 的 root 是一个道理）。

    密码写在 config 里、并优先读 .env 的 ADMIN_INIT_PASSWORD，
    这样正式部署时可以改掉默认值，而不用改代码。
    """
    from backend.app.config import ADMIN_INIT_PASSWORD, ADMIN_INIT_USERNAME

    exists = db.query(User).filter(User.username == ADMIN_INIT_USERNAME).first()
    if exists:
        return

    db.add(
        User(
            username=ADMIN_INIT_USERNAME,
            password_hash=hash_password(ADMIN_INIT_PASSWORD),
            name="管理员",
            email="admin@datasheet.local",
            role=ROLE_ADMIN,
            status=STATUS_ACTIVE,
            created_at=now(),
        )
    )
    db.commit()
