# -*- coding: utf-8 -*-
"""
users 表 —— 账号（管理员和普通用户共用一张表）
==============================================
为什么管理员不单独一张表：
    两边字段完全一样（都是用户名+密码+名字+邮箱+状态），登录逻辑也完全一样。
    拆成 admin / user 两张表的唯一后果是：每次"按用户名查一下"都要查两遍，
    以后加字段要加两处，迟早漏一处。用 role 字段区分就够，这也是一般后台系统的做法。

⚠️ status 和 role 都是**字符串枚举**而不是布尔：
    布尔只能表达两个状态，一旦以后要加"待审核"就没地方放了。
    字符串可读性也好 —— 直接看数据库就能懂，不用记 0/1 是什么意思。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base

# 角色取值
ROLE_ADMIN = "admin"
ROLE_USER = "user"

# 账号状态取值
STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # unique=True 让数据库自己保证账号不重复 —— 而不是靠代码先查一次再插。
    # 代码查一次会有并发窗口（两个请求同时查到"不存在"然后都插进去）。
    # index=True 是因为登录时就是按 username 查的，加索引避免全表扫描。
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))

    name: Mapped[str] = mapped_column(String(64), default="")
    email: Mapped[str] = mapped_column(String(128), default="")

    role: Mapped[str] = mapped_column(String(16), default=ROLE_USER)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_ACTIVE)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    # 可空：用户从没登录过就是 None（不是 空字符串，空字符串在数据库里是"有值但为空"，
    # 语义不清；None 才是"没有"）
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        """打印对象时显示成 <User id=1 username=admin role=admin>，
        调试时比 <User object at 0x...> 有用得多。"""
        return f"<User id={self.id} username={self.username} role={self.role}>"
