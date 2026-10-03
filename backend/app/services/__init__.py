# -*- coding: utf-8 -*-
"""
业务层（Service 层）
====================
这里放**编排逻辑**：把底层能力（检索、生成）按业务流程串起来。

现在有：
    rag_service.py    RAG 的完整一问一答：检索 -> 拼 prompt -> 调模型 -> 整理出处

原则：
    路由层（api/）不认识向量库，生成层（generation/）不认识检索 ——
    把它们粘在一起的活属于这里。这样一来，命令行、Streamlit、网页三个入口
    都只需要 `from backend.app.services.rag_service import get_engine`，
    不会出现"三个地方各写一份几乎一样的逻辑、改一处漏两处"。
"""
