# -*- coding: utf-8 -*-
"""
全局配置中心（全项目唯一的"项目根"定义处）
==========================================
为什么要有这个文件：
    脚本一旦被搬到更深的目录，`Path(__file__).resolve().parents[N]` 就会算错 ——
    N 是几完全取决于这个文件埋得多深。这正是"重构完就烂掉"的头号原因。

    所以全项目只在**这一个文件**里数一次层数，其他地方一律这样拿：

        from backend.app.config import ROOT, STORE_DIR, ENV_FILE

    以后目录再怎么调整，也只有这一个文件需要改。

职责边界：
    只放"常量与配置"，**不放任何业务逻辑**。
    判断标准：这个文件应该能被任何模块 import，而它自己不 import 任何业务模块
    （否则就会形成循环 import）。
"""
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------- 路径
# 本文件位置：backend/app/config.py
#   parents[0] = app
#   parents[1] = backend
#   parents[2] = 项目根   ← 我们要的就是它
ROOT = Path(__file__).resolve().parents[2]

BACKEND_DIR = ROOT / "backend"        # 后端代码
DATA_DIR = ROOT / "data"              # PDF 解析 / 清洗 / 切块的中间产物
DATASHEETS_DIR = ROOT / "datasheets"  # 原始 PDF
STORE_DIR = ROOT / "vectorstore"      # FAISS 向量库
EVAL_DIR = ROOT / "eval"              # 评测集 qa_pairs*.json
ENV_FILE = ROOT / ".env"              # 密钥文件（已在 .gitignore 里）

# 读取 .env 里的 DEEPSEEK_API_KEY / ZHIPUAI_API_KEY。
# 放在模块顶层：任何模块只要 import 了 config，密钥就已经就绪，不用各自再写一遍。
# 显式传 ENV_FILE 而不是用 load_dotenv() 的空参形式 ——
# 空参形式是按"当前工作目录"找 .env，换个目录敲命令就找不到了。
load_dotenv(ENV_FILE)

# ---------------------------------------------------------------- 模型
# ⚠️ EMBED_MODEL 必须和建库时用的完全一致。
#    换了嵌入模型，向量空间的坐标系就变了，检索结果会整体错乱 —— 而且不报错，只是答得离谱。
EMBED_MODEL = "embedding-3"      # 智谱嵌入模型
LLM_MODEL = "deepseek-chat"      # DeepSeek 对话模型

# ---------------------------------------------------------------- 检索参数
DEFAULT_K = 10                   # 默认检索块数（保持原行为）
# L2 距离阈值：越小越相似，典型有效范围 1.0~1.5，需要实验。
# None = 不启用（保持旧行为）。传了值会先取 k*3 块、过滤掉距离过大的，再截前 k 块。
DEFAULT_SCORE_THRESHOLD: float | None = None

# ---------------------------------------------------------------- 服务
API_TITLE = "Datasheet RAG API"
API_VERSION = "1.0"
HOST = "127.0.0.1"
PORT = 8000

# CORS 白名单：浏览器默认禁止跨源请求（前端 5173 调后端 8000 就属于跨源）。
# "null" 是为了兼容"双击打开本地 html"—— file:// 协议的 Origin 是字符串 null 而不是网址。
# ⚠️ 生产环境必须改成真实域名，否则任何网站都能调你的接口、花你的 API Key。
CORS_ORIGINS = [
    "null",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

# ---------------------------------------------------------------- 数据库（预留）
# 现在还没建表，database.py 也就没被 main.py 引用。
# 等你要加"文档记录 / 问答日志 / 用户"时，把 database.py 接进路由即可。
DB_FILE = DATA_DIR / "app.db"                      # SQLite：整个库就是一个文件，零安装
DATABASE_URL = f"sqlite:///{DB_FILE}"              # SQLAlchemy 的连接串写法
# 以后换 PostgreSQL 只改这一行，例如：
#   DATABASE_URL = "postgresql+psycopg://user:pass@localhost:5432/datasheet"
