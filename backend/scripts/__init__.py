# -*- coding: utf-8 -*-
"""
运维脚本（手动跑的，不参与线上服务）
====================================
和 app/ 里代码的区别：

    app/       线上服务的组成部分，被 uvicorn import
    scripts/   你自己敲命令跑的工具，跑完看输出，不常驻

现在有：
    chat.py                 命令行问答（最快验证链路通不通）
    streamlit_app.py        Streamlit 网页问答（备用的简易界面）
    evaluate.py             跑评测集，算答案包含率 + 检索命中率
    test_llm.py             验证 DeepSeek 密钥能不能调通（一次性）
    diag_crosslingual.py    中文提问 vs 英文提问的召回对比（诊断）
    scan_quality.py         全量扫描清洗产物的质量问题（诊断）
    compare_pdfplumber.py   当年选型的对比证据（pdfplumber vs PyMuPDF）

运行方式（**在项目根目录**，两种都行）：

    python -m backend.scripts.chat            # 推荐：能 import 到 backend 包
    python backend/scripts/chat.py            # 也可以：这些脚本自带 sys.path 兜底

⚠️ 这里的脚本每个开头都有两行 sys.path 注入。这是**入口脚本的特权**：
   它们要知道项目根在哪，才能 import 到 backend.app.*。
   反过来说，app/ 里的模块绝不能这么写 —— 一旦模块自己改 sys.path，
   "谁 import 谁"就变得不可预测，这才是真正的乱源。
"""
