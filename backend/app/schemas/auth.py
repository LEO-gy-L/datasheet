# -*- coding: utf-8 -*-
"""
认证接口的数据契约（入参校验 + 出参文档）
========================================
这里只放**入参**的校验模型。出参（响应）故意不写 response_model，原因很实在：

    出参的字段名要与前端 frontend/src/mock/data.js 里那份假数据**逐字符一致**，
    前端页面才能一行不改地跑（比如 createdAt、lastLogin 这些驼峰命名）。
    用 Pydantic 出参模型的话，字段一多就要写两遍定义（模型里一遍、组装字典时一遍），
    改一个字段名容易漏改一处，反而更容易出错。
    所以约定：**入参用 Pydantic 挡住脏数据，出参在 service 里组装成字典直接返回。**

⚠️ 入参的字段名跟前端传的 JSON 完全一致（驼峰），不是 Python 的蛇形命名。
    FastAPI 按字段名解析请求体，改字段名 = 前端立刻报 422。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """POST /api/auth/login 的请求体"""

    # min_length=1 挡掉空字符串。不设 max_length 也没关系 —— 但留个 64 位上限，
    # 防止有人塞一兆的字符串进来做无意义的哈希运算（每次哈希要 50~100ms，很贵）。
    username: str = Field(..., min_length=1, max_length=64, description="登录账号")
    password: str = Field(..., min_length=1, max_length=128, description="明文密码")


class ChangePasswordRequest(BaseModel):
    """PUT /api/auth/password（用户改自己的密码）"""

    # 前端 api/auth.js 里传的就是这两个驼峰字段名
    oldPassword: str = Field(..., min_length=1, description="当前密码，用来验证身份")
    newPassword: str = Field(..., min_length=6, max_length=128, description="新密码，至少 6 位")


class UpdateProfileRequest(BaseModel):
    """PUT /api/auth/profile（改自己的名字 / 邮箱）"""

    name: str = Field(..., min_length=1, max_length=64)
    email: str = Field("", max_length=128)
