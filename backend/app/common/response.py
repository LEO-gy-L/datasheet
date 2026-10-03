# -*- coding: utf-8 -*-
"""
统一响应格式
============
给**以后的 CRUD / 数据库接口**用（文档管理、问答日志、用户），
格式与 lab-agent 对齐：

    {"code": 0, "message": "ok", "data": {...}}

code 的约定：
    0        成功
    非 0     业务失败（HTTP 状态码仍然是 200，由 code 表达失败 —— 这是国内接口的常见风格）

⚠️ 现有的 /api/ask 和 /api/health **故意不套这一层**，原因很实在：
   前端 frontend/ 的 js 已经在按 {"answer","sources","seconds"} 直接取值，
   现在给它们套上 data 外壳 = 前端立刻白屏。要改就前后端一起改。

所以本文件现在的状态是"已备好、待使用"，和 database.py 一样 —— 不是死代码，
是下一步做数据库功能时的地基。
"""
from __future__ import annotations

from typing import Any


def ok(data: Any = None, message: str = "ok") -> dict:
    """成功响应。code 恒为 0。

    data 用 Any 而不是 dict：列表、字符串、数字都可能是合法的返回内容，
    强行要求 dict 会让调用方多套一层 {"items": [...]}，没必要。
    """
    return {"code": 0, "message": message, "data": data}


def fail(message: str = "error", code: int = 1, data: Any = None) -> dict:
    """失败响应。code 非 0，由调用方（前端）判断具体怎么处理。"""
    return {"code": code, "message": message, "data": data}
