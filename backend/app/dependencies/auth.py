# -*- coding: utf-8 -*-
"""
认证依赖：从请求头里认出"现在是谁"
==================================
FastAPI 的依赖注入在这里的作用：**任何接口只要在函数签名里写一句**

    user: User = Depends(get_current_user)

就自动拥有了"必须登录才能访问"的能力，而且能拿到当前用户对象。
不用每个接口自己解析 Authorization 头 —— 这种重复代码写十遍必然有一遍写错。

    admin: User = Depends(require_admin)

则表示"必须是管理员"，普通用户访问会拿到 403。

为什么要查一次数据库（而不是只信 token 里的 role）：
    token 里确实带了 role，但那是签发时的快照。管理员**禁用**某个账号后，
    如果只看 token，那个用户还能继续用 12 小时 —— 这显然不对。
    每次查一次库，才能让"禁用"立刻生效（代价是一次 SQLite 主键查询，微秒级）。
    顺便也解决了"用户被删了但 token 还在"的情况。
"""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models.user import ROLE_ADMIN, STATUS_ACTIVE, User
from backend.app.security.token import decode_token

# Authorization 头的标准格式是 "Bearer <token>"，中间一个空格。
# 大小写不敏感（RFC 规定 scheme 不区分大小写），所以用 .lower() 判断。
BEARER_PREFIX = "bearer "


def _extract_token(authorization: str | None) -> str:
    """从请求头里抠出 token 本身，抠不到就 401。

    401 与 403 的区别（这个一定要分清，前端要按它决定跳不跳登录页）：
        401 Unauthorized  = **你是谁我不知道** → 没登录 / token 过期 → 前端该踢回登录页
        403 Forbidden     = 我知道你是谁，但**你没权限** → 前端该提示"权限不足"，不该踢人
    """
    if not authorization or not authorization.lower().startswith(BEARER_PREFIX):
        raise HTTPException(status_code=401, detail="未登录")
    return authorization[len(BEARER_PREFIX):].strip()


def get_current_user(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> User:
    """解析 token -> 查出用户 -> 顺手检查账号是否被禁用。

    参数名 authorization 会自动映射到请求头 "Authorization"
    （FastAPI 的规则：下划线转连字符、大小写不敏感），不用手写 "Authorization"。
    """
    token = _extract_token(authorization)
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")

    # int() 可能失败：token 是我们自己签的，正常不会有问题；
    # 但万一密钥换了、或者有人拿别的系统签的 token 来试，这里就会崩。
    # 崩成 500 很难看，兜成 401 才对。
    try:
        user_id = int(payload.get("sub", ""))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="登录凭证无效") from None

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="账号不存在，请重新登录")
    if user.status != STATUS_ACTIVE:
        raise HTTPException(status_code=403, detail="账号已被禁用，请联系管理员")

    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """在 get_current_user 基础上再要求 role 必须是 admin。

    写成依赖而不是在每个接口里写 if，好处是权限要求**在校验阶段就统一拦掉**，
    漏写的风险只在"是否记得加这个依赖"这一处（而不是记得写 if）。
    """
    if user.role != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
