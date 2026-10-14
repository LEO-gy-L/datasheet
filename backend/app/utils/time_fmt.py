# -*- coding: utf-8 -*-
"""时间格式化：把 datetime 变成前端直接能显示的中文格式。

为什么单独抽一个函数而不是每个 service 各写一遍：
    前端的 mock 数据里，时间长这样 —— "2026-10-03 15:20"。
    页面组件是直接把它塞进表格里显示的（没有再格式化）。
    所以后端的返回值必须**逐字符一致**，否则界面上会冒出
    "2026-10-03T15:20:33.123456" 这种没人想看的字符串。

    这个格式只在这一个地方定义，以后想改（比如加秒）只改这里。

为什么不在 Pydantic schema 里用序列化器统一转：
    因为那样 datetime 会被转成 ISO 格式（带 T 和微秒），还得再写一层覆盖 ——
    不如在 service 组装返回值时就转好，一眼能看出返回给前端的到底是什么。
"""
from __future__ import annotations

from datetime import datetime

FORMAT = "%Y-%m-%d %H:%M"


def fmt(dt: datetime | None) -> str:
    """None 一律返回空字符串。

    为什么不是返回 None：前端拿到的就是字符串（mock 里空值也是 ""），
    返回 None 会让 React 把 "null" 渲染出来或者报错。
    空字符串最省事 —— 页面上就是空着，什么也不显示。
    """
    if dt is None:
        return ""
    return dt.strftime(FORMAT)


def now() -> datetime:
    """当前时间。

    单独包一层是为了将来要统一改成 UTC 时只改这一处。
    现在用本地时间（Windows 上就是北京时间），因为界面是给人看的，
    显示本地时间最直观。
    """
    return datetime.now()
