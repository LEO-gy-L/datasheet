# -*- coding: utf-8 -*-
"""
路由层（API 层）
================
一个文件 = 一组相关接口（lab-agent 就是按业务分的：auth.py / user.py / lab.py ...）。
每个文件里定义一个 `router`，最后在 main.py 里统一 `include_router` 挂上去。

**路由层的铁律：只做三件事**
    1. 收参数（靠 schemas 里的 Pydantic 模型校验）
    2. 调 service（业务逻辑全在 services/ 里）
    3. 转异常（把业务异常翻成 HTTP 状态码）

一旦发现自己在路由函数里写 for 循环处理数据、或者拼 SQL，
说明这段逻辑该下沉到 services/ —— 否则命令行、Streamlit、网页三个入口就会各写一份。

现在有：
    qa.py   GET /api/health、POST /api/ask

下一步（做数据库功能时）：
    documents.py   上传 / 列表 / 删除手册
    history.py     问答历史
"""
