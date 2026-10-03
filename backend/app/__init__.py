# -*- coding: utf-8 -*-
"""
应用包（Application）
=====================
后端所有**代码**都住在 backend/app/ 下，对外只暴露一个入口：

    backend.app.main:app      ← uvicorn 加载的就是这个（start_backend.bat 里那一行）

分层一览（从上到下 = 一次请求流过的顺序）：

    api/            路由层：收参数、调 service、转异常，不写业务
    schemas/        契约层：请求/响应的字段定义与自动校验
    services/       业务层：RAG 的编排（检索 -> 拼 prompt -> 调模型）
    dependencies/   注入层：把"共享对象"（引擎、以后的当前用户）递给接口
    retrieval/      检索层：向量化、混合检索、重排
    generation/     生成层：大模型客户端与 prompt 模板
    ingestion/      入库层：PDF -> 清洗 -> 切块 -> 向量库（离线跑，不在请求链路上）
    models/         数据层：数据库表（ORM），目前为空
    common/         公共层：自定义异常、统一响应格式
    utils/          工具层：与业务无关的纯函数，目前为空
    config.py       配置中心：全项目唯一的"项目根"定义处
    database.py     数据库连接（已备好，未接入）
    main.py         应用装配：创建 FastAPI、挂中间件、注册路由

为什么 lifespan / 分层这么切，见各文件头部注释。
"""
