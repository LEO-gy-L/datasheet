# -*- coding: utf-8 -*-
"""
用户管理接口的数据契约（管理员操作**别人**的账号）
================================================
⚠️ 跟 schemas/auth.py 的区别（这两套很容易混）：

    schemas/auth.py    用户在「用户信息」页改**自己**的密码 → PUT /api/auth/password
    schemas/user.py    管理员在「账号管理」页重置**别人**的密码 → PUT /api/users/{id}/password

    为什么分两套接口而不是合并成一个"改密码"：
      ① 权限不同：改自己只要登录，改别人要管理员
      ② 要验证的东西不同：改自己必须提供旧密码；管理员重置不需要（他就是来救急的，
         用户忘了密码才来找他，旧密码本来就不知道）
      ③ 审计不同：管理员动别人的密码是敏感操作，将来要单独记操作日志

    合并成一个接口的话，里面就得写"如果是自己就验旧密码、否则查是不是管理员"，
    这种一个接口两种行为的写法后面极难维护。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class UserPatch(BaseModel):
    """PUT /api/users/{id} —— 改资料。

    字段全部可选（默认 None）= 局部更新：前端只传想改的那几个字段，
    没传的字段保持原值。如果做成"全都要传"，那么只改名字也得把邮箱一起带上，
    前端不小心忘了传某字段就会把它清空 —— 这类 bug 很隐蔽。
    """
    username: str | None = Field(None, min_length=1, max_length=64)
    name: str | None = Field(None, max_length=64)
    email: str | None = Field(None, max_length=128)


class PasswordReset(BaseModel):
    """PUT /api/users/{id}/password —— 管理员重置密码。不需要旧密码。"""

    password: str = Field(..., min_length=6, max_length=128, description="新密码，至少 6 位")


class StatusPatch(BaseModel):
    """PUT /api/users/{id}/status —— 启用 / 禁用账号。

    用 Literal 限制只能传这两个值：传 "ban" 之类的会直接被 FastAPI 挡成 422，
    不用自己写 if 判断。
    """

    status: Literal["active", "disabled"]
