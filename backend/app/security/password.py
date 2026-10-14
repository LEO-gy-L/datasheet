# -*- coding: utf-8 -*-
"""
密码哈希与校验
==============
为什么不存明文：数据库文件一旦泄漏，明文密码等于把所有账号送出去。
而且人在多个网站爱用同一个密码 —— 泄漏会波及他自己别的账号。
所以数据库里存的是"算不回去"的东西：**哈希**。

算法：PBKDF2-HMAC-SHA256，20 万轮，每个用户一个独立随机盐。

为什么用标准库而不是 bcrypt / passlib：
    这个项目的 venv 是 **uv** 建的，**没有 pip**（`python -m pip` 会报
    No module named pip），装 bcrypt 得多绕一步。而 `hashlib.pbkdf2_hmac`
    是 Python 标准库、Django 默认就用它，安全性完全够。
    以后要是修好 pip 想换成 bcrypt，只改本文件这两个函数即可 ——
    因为存储格式里自带算法前缀，可以两种算法并存、平滑过渡。

存储格式（一段字符串自解释，不需要数据库里再多一个"算法"字段）：

    pbkdf2_sha256$200000$<盐的 hex>$<哈希的 hex>
    └─ 算法 ────┘ └轮数┘ └─ 16 字节 ─┘ └─ 32 字节 ─┘

校验时从字符串里把盐和轮数读出来，用同样的参数重算一遍，再**常量时间**比较。

⚠️ 两个必须做对的点：
    ① 盐必须随机且每个用户不同 —— 否则两个相同密码会得到相同哈希，
       攻击者可以拿一张"常见密码哈希表"一次性撞开所有账号。
    ② 比较必须用 hmac.compare_digest 而不是 == ——
       普通字符串比较在第一个不同的字符处就返回，耗时随匹配长度变化，
       理论上可以被"逐字节试探"（时序攻击）。虽然实战里很难利用，但这行代码一样长，没理由不写对。
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 200_000      # 20 万轮。单次约 50~100ms —— 登录能忍，暴力破解很疼
SALT_BYTES = 16           # 盐 16 字节 = 128 位，随机到不可能重复
KEY_BYTES = 32            # 结果 32 字节 = 256 位，和 SHA-256 输出等长


def hash_password(password: str) -> str:
    """把明文密码变成可入库的哈希字符串。每次调用结果都不同（因为盐是随机的）。"""
    salt = secrets.token_bytes(SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        ITERATIONS,
        dklen=KEY_BYTES,
    )
    return f"{ALGORITHM}${ITERATIONS}${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验明文密码是否与库里存的哈希匹配。

    任何格式不对的情况（用户没设密码、字段被手改坏了）都返回 False，
    **不抛异常** —— 调用方只想得到一个"是/否"，不需要处理解析失败。
    """
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != ALGORITHM:
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        rounds = int(iterations)
    except (ValueError, AttributeError):
        return False

    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        rounds,
        dklen=len(expected),
    )
    return hmac.compare_digest(derived, expected)
