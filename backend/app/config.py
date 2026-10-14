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
import os
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

# ---- 入库流水线的三道中间产物目录（2026-10-03 新增）----
# 加在这里而不是在服务层现算，理由和本文件开头的说明一样：
#   目录名一旦有多处副本，改动时漏掉一处，症状是"解析产物在 A 目录、
#   切块却去 B 目录找" —— 报"找不到产物"，但两个目录各自看都是对的。
# ⚠️ 目录名后面那个 v2 / v5 是**版本号**，不是随手起的：
#    改了清洗规则之后要换版本号重跑，好让新老产物并存、可对比、可回退。
#    所以这三个值**不能**合并成同一个变量。
TEXT_DIR = DATA_DIR / "text_v2"       # 正文清洗产物：text_v2/<stem>/page_XXXX.md
TABLE_DIR = DATA_DIR / "tables_v5"    # 表格清洗产物：tables_v5/<stem>/page_XXXX.md
CHUNKS_DIR = DATA_DIR / "chunks_v2"   # 切块产物：chunks_v2/<stem>/chunks.jsonl

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

# ---------------------------------------------------------------- 混合检索
# 完整链路（见 retrieval/hybrid.py 文件头的流程图）：
#     两路召回 -> RRF 融合 -> 重排 -> 取 Top-N -> 父块放大
#
# 每个参数为什么是这个值，都在 hybrid.py 里对相应的常量写了注释。
# 这里只放"旋钮"，不放逻辑 —— 调效果时只改这个文件。
RECALL_DENSE = 10                # ①「语义路」召回的候选数
RECALL_BM25 = 10                 # ①「关键词路」召回的候选数
FUSED_TOP = 10                   # ② RRF 融合后，放进重排池的条数（= 你说的"召回10个块"）
RERANK_TOP_N = 3                 # ③ 重排后真正送给大模型的条数
RRF_K = 60                       # RRF 平滑常数。60 是原论文的推荐值，见 hybrid.py 说明
BM25_K1 = 1.5                    # BM25 词频饱和参数（决定"重复出现还有没有增益"）
BM25_B = 0.75                    # BM25 长度归一化强度（0=不归一化，1=完全归一化）

# 要放大到"父块"吗？
#   True  -> 命中一个碎片，把整个章节/整张表一起送给模型（上下文完整，多花 token）
#   False -> 只送命中的那一小块（省 token，但可能缺上下文）
# 评测时可以两种都跑一遍对比分数，所以做成开关而不是写死。
EXPAND_PARENT = True

# ---------------------------------------------------------------- 重排（智谱 rerank）
# 为什么用单独的 HTTP 请求而不是 SDK：
#   zhipuai 2.1.5 这个版本的 Python SDK 没有封装 rerank 方法（实测 dir(client) 里没有），
#   但接口本身是通的，所以直接打 HTTP。
RERANK_ENABLED = True
RERANK_URL = "https://open.bigmodel.cn/api/paas/v4/rerank"
RERANK_MODEL = "rerank"
RERANK_TIMEOUT = 20.0            # 秒。网络慢时不至于把整个接口卡死
RERANK_MAX_DOC_CHARS = 1200      # 单条候选送去重排前截断的长度（接口上限 4096，留余量）
RERANK_SOURCE = "index_text"     # 拿哪份文字去重排：index_text（检索优化过的）或 content（原文）

# ⚠️ 这个开关**必须**是 True，下面是 2026-10-03 实测的对比数据，不要随手改成 False。
#
# 智谱 rerank 默认返回的 relevance_score 是 sigmoid 归一化后的值，会**饱和在 0.99~1.0**。
# 同一批 10 条候选的实测结果：
#
#     return_raw_scores=False          return_raw_scores=True
#     ------------------------         -----------------------
#     1.00000000  (图形块 p11)          24.26562500  (表格块 表1-1  ← 正确答案在这里)
#     1.00000000  (图形块 p4)           18.23437500  (图形块 p3)
#     1.00000000  (图形块 p3)           18.15625000  (图形块 p11)
#     1.00000000  (正文 p23)            18.12500000  (图形块 p4)
#     1.00000000  (表格块 表1-1)         17.28125000  (正文 p23)
#     ...                               ...
#
# 左列看不了：所有分都是 1.00000000，排序完全由小数点后第 7 位决定，等于噪声，
#           结果就是"引脚图"把"引脚数"挤下去，含答案的表格块被挤出 Top-3。
# 右列一目了然：表格块 24.27 遥遥领先，排序完全正确。
RERANK_RETURN_RAW = True

# 图形「指针块」的重排分折扣（0~1，1 = 不打折）。
#
# 为什么需要这个：
#     ingestion 阶段给"矢量框图"生成的是**指针块**，文本形如
#         "本页含 1 幅矢量图形（框图 / 引脚图 / 时序图），区域：……本块不包含任何图形内容"
#     这段话里天然带着"引脚图""框图""时序图"这些词 —— 用户问"引脚数是多少"时，
#     重排模型看到"引脚图"会给一个不低的分，于是三张图形块能一起挤进 Top-3，
#     把真正含数据的表格挤出去。
#
# 这也正是你说的"矢量框图当指针用，不当内容"在检索层的落地：
#     指针块不该和内容块竞争"谁更相关"，它的价值是**告诉你去哪一页看图**，
#     而不是**回答问题本身**。所以给它一个先验折扣。
#
# 取 0.5 是打五折：实测图形块原始分 18.2，打折后 9.1，会落到所有内容块之后；
# 但如果问题真的是"引脚图在第几页"（这时内容块分数都很低，比如 5 分），
# 图形块即使打了折仍会排在前面 —— 该召回的时候照样召回。
FIGURE_SCORE_PENALTY = 0.5

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

# ---------------------------------------------------------------- 认证（2026-10-03 新增）
# JWT 签名密钥。**正式部署必须在 .env 里覆盖它**：
#   ① 用默认值的话，任何看过这份源码的人都能自己签一张管理员 token
#   ② 反过来，密钥一旦更换，所有已发出的 token 立刻失效（用户需要重新登录）——
#      这是它的工作方式，不是 bug
# 生成一个随机密钥：python -c "import secrets; print(secrets.token_urlsafe(32))"
JWT_SECRET = os.getenv("JWT_SECRET", "dev-only-insecure-secret-change-me")

# HS256 = HMAC + SHA256。单机服务用它最简单：一把密钥既签又验，不需要非对称密钥对。
# 换 RS256 的场景是"签发方和验证方不是同一个服务"，我们不是。
JWT_ALGORITHM = "HS256"

# 12 小时：够覆盖一个工作日的连续使用，又不至于长期有效。
# ⚠️ JWT 的代价在这里体现：没有"立刻踢人下线"的能力，改密码后旧 token 仍然有效到过期。
#    对课程项目够用；真要做强制下线，得额外维护一张"已登出 token"表。
TOKEN_EXPIRE_MINUTES = 60 * 12

# 首次启动自动创建的管理员账号。
# 数据库建好之后是空的 —— 没有这个种子账号就**谁也进不去系统**，
# 而"登录之后才能创建账号"是个鸡生蛋问题，所以默认管理员必须由程序自己建。
# 正式部署时把 ADMIN_INIT_PASSWORD 写进 .env，改密码而不用改代码。
ADMIN_INIT_USERNAME = os.getenv("ADMIN_INIT_USERNAME", "admin")
ADMIN_INIT_PASSWORD = os.getenv("ADMIN_INIT_PASSWORD", "admin123")
