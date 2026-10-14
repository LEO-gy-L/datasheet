# -*- coding: utf-8 -*-
"""
JWT 令牌的签发与解析
====================
要解决的问题：HTTP 是**无状态**的 —— 服务器不记得"上一秒是谁在跟我说话"。
所以要么每个请求都带一次账号密码（糟糕），要么给浏览器发一张**通行证**，之后每次请求亮一下。

JWT 就是这张通行证。它长这样（三段，点号分隔）：

    eyJhbGciOiJIUzI1NiJ9 . eyJzdWIiOiIxIiwicm9sZSI6ImFkbWluIn0 . 签名
    └── 头部：用什么算法 ─┘ └──── 载荷：内容（明文！） ────┘   └ 防篡改 ─┘

⚠️ 最容易搞错的一点：**载荷是能被任何人解开的**（只是 base64，不是加密）。
   所以里面**绝对不能放密码、密钥**这类东西。我们只放三个无害信息：
   sub（用户 id）、username、role。
   它的安全性来自最后那段**签名**：没有密钥就改不了载荷，
   改了签名就对不上，服务端一验就知道被篡改过。

为什么不用"服务端存一个 session 表"的办法：
    JWT 不需要查库就能验身份（验签 + 看过期时间），适合这种单机小服务；
    session 表的好处是能"立刻踢人下线"，JWT 只能等它自己过期 ——
    这个取舍对我们够用（admin 禁用账号后，用户最多等 token 过期，实测 12 小时）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt

from backend.app.config import JWT_ALGORITHM, JWT_SECRET, TOKEN_EXPIRE_MINUTES


def create_token(user_id: int, username: str, role: str) -> str:
    """签一张 12 小时有效的通行证。

    时间一律用 UTC（timezone.utc）而不是本地时间：
    JWT 的 exp 校验是拿两边的时间戳做比较，服务器时区一乱就会出现
    "刚登录就说过期"这种玄学问题。存 UTC 是行业惯例。
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),                    # subject：这张通行证属于谁
        "username": username,
        "role": role,
        "iat": now,                             # issued at：签发时间
        "exp": now + timedelta(minutes=TOKEN_EXPIRE_MINUTES),   # expire：过期时间
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    """验签 + 检查过期。

    失败一律返回 None，**不抛异常** —— 调用方（依赖层）只需要判断"通不通过"，
    具体是过期还是被篡改对它没区别，都是 401 打回登录页。

    jwt.decode 会自己检查 exp：过期会抛 ExpiredSignatureError（属于 PyJWTError）。
    """
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
