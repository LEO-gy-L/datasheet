# Datasheet 智能问答系统

芯片数据手册智能问答：把 PDF 数据手册丢进 `datasheets/` 文件夹，
就能用自然语言提问（如"GPIO 最大输出电流多少"），系统检索原文后由 DeepSeek 生成答案，并给出来源**和页码**。

技术栈：Python + PyMuPDF + LangChain + FAISS + 智谱 Embedding（免费）+ DeepSeek + FastAPI + 前端网页

---

## 目录结构

```
datasheet/
├── .env                       ← 填你的两个 API Key（不要外传）
├── requirements.txt           ← 依赖清单
├── start_backend.bat          ← 双击启动后端服务
├── datasheets/                ← 原始数据手册 PDF
├── data/                      ← 管线中间产物（可随时删掉重跑）
│   ├── tables_v5/<手册名>/    ← 清洗后的表格页（ingestion/tables.py 产出）
│   ├── text_v2/<手册名>/      ← 清洗后的正文页（ingestion/text.py 产出）
│   └── chunks_v2/<手册名>/    ← 切块结果 chunks.jsonl（ingestion/chunking.py 产出）
├── vectorstore/               ← 向量库（ingestion/indexer.py 产出，含 _manifest.json 建库清单）
├── eval/                      ← 评测集 qa_pairs.json / qa_pairs_v2.json
├── backend/                   ← 全部 Python 代码
│   ├── app/                   ← 线上服务（uvicorn 加载的就是这里）
│   ├── scripts/               ← 手动跑的工具（问答、评测、诊断）
│   └── legacy/                ← 已废弃脚本，只留作对比证据
└── frontend/                  ← 网页界面（Vite + React，npm run dev 启动）
```

## backend/app/ 分层：一次提问流过哪些层

```
用户提问
   │
   ▼
api/qa.py          路由层：收参数、调 service、把业务异常翻成 HTTP 状态码
   │  ↕ schemas/qa.py   契约层：AskRequest / AskResponse（自动校验 + 自动生成 /docs）
   │  ↕ dependencies/engine.py  注入层：把"唯一的引擎实例"递进来（不每次重建）
   ▼
services/rag_service.py   业务层：检索 → 拼 prompt → 调模型 → 整理出处
   │  ↕ common/exceptions.py  业务异常（EmptyQuestion / IndexNotFound / ModelCall）
   ▼
retrieval/embeddings.py   检索层：把问题向量化（与入库用的是同一个模型）
generation/prompts.py     生成层：prompt 模板（改措辞只改这里）
generation/llm.py         生成层：DeepSeek 客户端工厂
   │
   ▼
回答（带来源页码）→ 返回给前端

—— 以上是"在线链路"。下面是"离线链路"，跑一次把结果存磁盘，问答时只读：

ingestion/tables.py ─┐
ingestion/text.py   ─┼→ ingestion/chunking.py → ingestion/indexer.py → vectorstore/
ingestion/figures.py ┘   （PDF→清洗）            （切块）            （向量化入库）
```

| 路径 | 职责 | 一句话记住它存在的理由 |
|---|---|---|
| `app/main.py` | FastAPI 应用装配（**后端入口**） | 只做装配：建 app、挂 CORS、注册路由、启动时预热引擎 |
| `app/config.py` | 配置中心 | **全项目唯一**数"项目根"在哪的地方，其他文件一律 `from backend.app.config import ROOT` |
| `app/database.py` | 数据库连接（SQLAlchemy） | 已备好未接入：建表、开会话都在这里，加数据库功能时直接用 |
| `app/api/` | 路由层 | 只收参数、调 service、转异常；不写业务 |
| `app/schemas/` | 契约层 | 请求/响应字段定义，Pydantic 负责自动校验与 /docs 文档 |
| `app/services/` | 业务层 | RAG 的编排，命令行 / Streamlit / 网页三个入口共用同一份 |
| `app/dependencies/` | 注入层 | 让接口"拿来就用"共享对象，也方便测试时替换成假对象 |
| `app/retrieval/` | 检索层 | 向量化 + （下一步的）混合检索、重排 |
| `app/generation/` | 生成层 | 模型客户端与 prompt 措辞 |
| `app/ingestion/` | 入库层 | PDF → 清洗 → 切块 → 向量库，离线跑 |
| `app/models/` | 数据层 | ORM 表（现在为空，建表步骤写在它的 `__init__.py` 里） |
| `app/common/` | 公共层 | 自定义异常 + 统一响应格式 |
| `app/utils/` | 工具层 | 与业务无关的纯函数（现在为空，等真需要再放） |
| `backend/scripts/` | 手动工具 | 问答、评测、诊断 —— 跑完看输出，不常驻 |
| `backend/legacy/` | 历史证据 | 已废弃脚本，**不要运行** |

### scripts/ 里每个脚本干什么

| 文件 | 作用 | 怎么跑（在项目根目录） |
|---|---|---|
| `chat.py` | 命令行问答（最快验证链路通不通） | `python -m backend.scripts.chat` |
| `evaluate.py` | 跑评测集，算答案包含率 + 检索命中率 | `python -m backend.scripts.evaluate --k 6` |
| `diag_crosslingual.py` | 中文提问 vs 英文提问的召回对比 | `python -m backend.scripts.diag_crosslingual` |
| `scan_quality.py` | 全量扫描清洗产物的质量问题 | `python -m backend.scripts.scan_quality` |
| `test_llm.py` | 验证 DeepSeek 密钥能不能调通 | `python -m backend.scripts.test_llm` |
| `streamlit_app.py` | Streamlit 备用界面 | `python -m streamlit run backend/scripts/streamlit_app.py` |
| `compare_pdfplumber.py` | 当年选型的对比证据 | 需先装 `pdfplumber`（不在 requirements 里，只为这一次对比用） |

> `legacy/step3_vectorstore.py` 是旧命令的壳：它自己啥也不干，只是转调
> `backend.app.ingestion.indexer`，让"老习惯"不失效。

> 历史说明：更早的旧线路脚本（`p0_1_tables_v3.py`、`p1_1_chunk.py`、`load_split.py` 等）
> 已经不在仓库里了。其中 `load_split.py` 的正则写错（`$$来源$$` 应为 `\[来源\]`）导致表格块全丢，
> 它的位置已被 `ingestion/chunking.py` 取代。

---

## 环境搭建（只需做一次）

```bash
# 1. 创建虚拟环境
python -m venv .venv

# 2. 安装依赖（阿里云镜像，快）
.venv\Scripts\python -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

## 配置密钥

打开 `.env`，填入：
- `DEEPSEEK_API_KEY`：https://platform.deepseek.com 申请（你已充值）
- `ZHIPUAI_API_KEY`：https://bigmodel.cn 申请（embedding 免费）

## 按顺序运行（数据管线 → 问答）

⚠️ **所有 `-m` 命令都必须在项目根目录执行**。`-m` 后面的点号就是"文件路径换成模块路径"：
`backend/app/ingestion/indexer.py` 写成 `backend.app.ingestion.indexer`。
（venv 已激活时直接用 `python`；没激活就写 `.venv\Scripts\python`。）

```bash
# 第0步：验证模型能通（看到回复 + token 用量即成功）
python -m backend.scripts.test_llm

# 第1步：表格 —— 提取 + 清洗 + 过滤伪表
python -m backend.app.ingestion.tables

# 第2步：正文 —— 提取 + 清洗
python -m backend.app.ingestion.text

# 第3步：切块 —— 正文按小节切、表格跨页合并后拆片
python -m backend.app.ingestion.chunking

# 第4步：建向量库（先 --dry-run 空跑看看会装什么，不调接口不花钱）
python -m backend.app.ingestion.indexer --dry-run
python -m backend.app.ingestion.indexer

# 第5步：开始问答！试试这些问题：
#   "GPIO 最大输出电流是多少？"
#   "VDD - VSS 之间允许的最大电压是多少？"
#   "这个芯片有几个定时器？"
python -m backend.scripts.chat
```

**重要**：换了数据手册（改了 `datasheets/` 里的文件）之后，上面第 1~4 步必须整体重跑一遍，
否则向量库里还是旧手册的内容。只看 `vectorstore/_manifest.json` 就能确认库里装的是哪份手册、多少块。

> 第 4 步用 `--stem STM32F103C8_Datasheet` 可以只索引某一份手册；
> `--limit 20` 可以只取前 20 块先跑通链路。
> 建库用的是 `embedding-3`，**必须和检索时一致**，换了模型要重建，否则检索结果整体错乱（而且不报错）。

## 推荐使用方式：自定义网页界面（前后端分离）

1. 双击项目根目录的 `start_backend.bat` → 弹出黑窗口，显示 `Uvicorn running on http://127.0.0.1:8000`
2. 另开一个终端，进前端目录启动开发服务器：
   ```bash
   cd frontend
   npm install     # 只需第一次
   npm run dev
   ```
3. 浏览器打开终端里提示的地址（默认 `http://localhost:5173`）即可提问
4. 想直接调接口：浏览器开 `http://127.0.0.1:8000/docs`，能看自动生成的接口文档并点 "Try it out" 提问
5. 用完关掉黑窗口即停止服务

> 架构说明：`backend/app/` 是后端（Python 干活），`frontend/` 是前端（负责好看），
> 两者通过 HTTP 通信。这就是工业界的"前后端分离"，也是简历上能写的一条。
>
> ⚠️ 访问 `http://127.0.0.1:8000/` 会返回 404 —— 这是正常的：后端只定义了
> `/api/health` 和 `/api/ask` 两个路由，没有根路径。正确入口是 `/docs`。

## 换成真实数据手册

1. 把 PDF 丢进 `datasheets/`
2. 重跑第 1~4 步（管线会自动读同名 stem 的目录）
3. 再跑第 5 步提问

中英文手册都行。ATmega328P 手册也能跑（清洗规则已在两种排版上交叉验证过）。

## 常见问题

| 报错 | 原因 | 解决 |
|---|---|---|
| `请先在 .env 文件里填入...` | 密钥没填 | 编辑 `.env` |
| 401 / Unauthorized | 密钥错了或欠费 | 去平台检查 key 和余额 |
| `[错误] 找不到 data/chunks_v2` | 上游没跑 | 按顺序跑第 1~3 步 |
| `embedding-3` 报错 | 智谱接口变动 | 把 `backend/app/config.py` 里的 `EMBED_MODEL` 改成 `embedding-2`，然后**重建向量库** |
| FAISS 的 `allow_dangerous_deserialization` 警告 | 官方安全要求 | 正常现象，自己的库自己加载 |
| 答案胡说 / 答的不是这份手册 | 向量库没跟着重建 | 重跑第 4 步；核对 `vectorstore/_manifest.json` 里的 `sources` |
| `ModuleNotFoundError: No module named 'backend'` | 不在项目根目录执行 | `cd` 到项目根再敲命令；`-m` 的模块路径是相对当前目录解析的 |
| 向量库不存在 | 还没建库 | 跑第 4 步（`python -m backend.app.ingestion.indexer`） |
| 接口返回 400 / 422 | 问题为空 / 超过 2000 字 | 400 是业务校验，422 是 Pydantic 字段校验，都是正常保护 |

> 关于路径：所有 `app/` 里的模块都从 `backend.app.config` 拿 `ROOT`，
> **全项目只在 `config.py` 里数一次层级**。以后目录再调整，只需改那一个文件。
> 只有 `backend/scripts/` 里的入口脚本会自己往 `sys.path` 里塞项目根（为了让
> `python backend/scripts/chat.py` 这种老写法也能跑），app/ 里的模块绝不这么做。

## 简历写法（项目描述参考）

> 基于 LangChain 的芯片数据手册 RAG 问答系统：用 PyMuPDF 从 PDF 中提取正文与表格，
> 做了页眉页脚剔除、跨页表格合并、合并单元格回填、表格标题坐标定位等清洗；
> 切块时给每块贴上"手册名 + 页码 + 章节路径/表格标题"的上下文前缀，
> 用智谱 embedding-3 向量化后存入 FAISS；用户提问时检索 top-k 片段注入 Prompt，
> 调用 DeepSeek 生成带页码溯源的回答；后端按 API / Service / Retrieval / Ingestion
> 分层组织（FastAPI + SQLAlchemy 预留数据层），前端为独立网页工程，提供完整交互界面。
