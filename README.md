# Datasheet 智能问答系统

芯片数据手册智能问答：把 PDF/TXT 数据手册丢进 `datasheets/` 文件夹，
就能用自然语言提问（如"GPIO 最大输出电流多少"），系统检索原文后由 DeepSeek 生成答案，并给出来源**和页码**。

技术栈：Python + PyMuPDF + LangChain + FAISS + 智谱 Embedding（免费）+ DeepSeek + FastAPI + 前端网页

## 目录结构

```
datasheet/
├── .env                       ← 填你的两个 API Key（不要外传）
├── requirements.txt           ← 依赖清单
├── datasheets/                ← 数据手册放这里（当前：STM32F103C8、ATmega328P、WB32F 示例）
├── data/                      ← P0/P1 管线的所有中间产物（可随时删掉重跑）
│   ├── tables_v5/<手册名>/    ← 清洗后的表格（p0_1_extract_tables.py 产出）
│   ├── text_v2/<手册名>/      ← 清洗后的正文（p0_2_extract_text.py 产出）
│   └── chunks_v2/<手册名>/    ← 切块结果 chunks.jsonl（chunk_loader.py 产出）
├── vectorstore/               ← 向量库（p1_2_index.py 产出；含 _manifest.json 建库清单）
├── src/                       ← 全部 Python 代码（见下表）
├── index.html + css/ + js/    ← 前端网页（前后端分离）
├── start_backend.bat          ← 双击启动后端服务
└── _backup_before_fix_20260929/ ← 2026-09-29 大修前的源码与产物备份，确认没问题后可删
```

### src/ 里每个文件干什么

| 文件 | 作用 | 读 | 写 |
|---|---|---|---|
| `p0_1_extract_tables.py` | 表格：提取 + 字符清洗 + 伪表过滤 + 合并单元格修复 | `datasheets/*.pdf` | `data/tables_v5/` |
| `p0_2_extract_text.py` | 正文：提取 + 剔页眉页脚/表格区/图内标签 + 段落合并 | `datasheets/*.pdf` | `data/text_v2/` |
| `chunk_loader.py` | 切块：正文按小节切、表格跨页合并 + 超长拆片，都带上下文前缀 | `data/tables_v5` + `data/text_v2` | `data/chunks_v2/` |
| `p1_2_index.py` | 向量化入库（**断链的那一环**） | `data/chunks_v2/**/chunks.jsonl` | `vectorstore/` |
| `step4_rag.py` | 命令行问答（核心） | `vectorstore/` | 只打印 |
| `api.py` | 后端接口（网页版依赖它） | `vectorstore/` | 只返回 JSON |
| `app.py` | Streamlit 版界面（可选） | `vectorstore/` | — |
| `step3_vectorstore.py` | 旧命令的壳，转调 `p1_2_index.py` | — | — |
| `llm.py` | 只验证 DeepSeek 能调通 | — | 只打印 |
| `p0_compare_pdfplumber.py` | 选型实验：pdfplumber vs PyMuPDF | `datasheets/*.pdf` | 只打印 |
| `p0_scan_quality.py` | 全量质量体检：合并单元格、残留占位列、脏标记 | `datasheets/*.pdf` + `data/tables_v5` | 只打印 |
| `src/legacy/` | **已废弃的旧线路脚本**，只留作对比证据，不要运行 | — | — |

> 关于 `src/legacy/`：里面是 `p0_1_tables_v3.py`、`p0_2_filter_tables.py`、`p0_3_text.py`、
> `p1_1_chunk.py`、`load_split.py`。旧线路产物是 `data/tables_v3`、`tables_v4`、`text_v1`、`chunks`。
> `load_split.py:75` 的正则写错（`$$来源$$` 应为 `\[来源\]`）导致表格块全丢，已被 `chunk_loader.py` 取代。

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

```bash
# 第0步：验证模型能通（看到回复+token用量即成功）
.venv\Scripts\python src\llm.py

# 第1步：表格 —— 提取 + 清洗 + 过滤伪表
.venv\Scripts\python src\p0_1_extract_tables.py

# 第2步：正文 —— 提取 + 清洗
.venv\Scripts\python src\p0_2_extract_text.py

# 第3步：切块 —— 正文按小节切、表格跨页合并后拆片
.venv\Scripts\python src\chunk_loader.py

# 第4步：建向量库（先 --dry-run 空跑看看会装什么，不调接口不花钱）
.venv\Scripts\python src\p1_2_index.py --dry-run
.venv\Scripts\python src\p1_2_index.py

# 第5步：开始问答！试试这些问题：
#   "GPIO 最大输出电流是多少？"
#   "VDD - VSS 之间允许的最大电压是多少？"
#   "这个芯片有几个定时器？"
.venv\Scripts\python src\step4_rag.py
```

**重要**：换了数据手册（改了 `datasheets/` 里的文件）之后，上面第 1~4 步必须整体重跑一遍，
否则向量库里还是旧手册的内容。只看 `vectorstore/_manifest.json` 就能确认库里装的是哪份手册、多少块。

> 第 4 步用 `--stem STM32F103C8_Datasheet` 可以只索引某一份手册；
> `--limit 20` 可以只取前 20 块先跑通链路。

## 推荐使用方式：自定义网页界面（前后端分离）

1. 双击项目根目录的 `start_backend.bat` → 会弹出黑窗口，显示 `Uvicorn running on http://127.0.0.1:8000`
2. 打开 `index.html` → 浏览器打开聊天界面，右上角显示"后端已连接"即可提问
3. 用完关掉黑窗口即停止服务

> 架构说明：`src/api.py` 是后端（Python 干活），`index.html` 是前端（负责好看），
> 两者通过 HTTP 通信。这就是工业界的"前后端分离"，也是简历上能写的一条。

## 换成真实数据手册

1. 把 PDF 丢进 `datasheets/`
2. 重跑第 1~4 步（管线会自动读同名 stem 的目录）
3. 再跑第 5 步提问

中英文手册都行。ATmega328P 手册也能跑（清洗规则已在两种排版上交叉验证过）。

## 常见问题

| 报错 | 原因 | 解决 |
|---|---|---|
| `请先在 .env 文件里填入...` | 密钥没填 | 编辑 .env |
| 401 / Unauthorized | 密钥错了或欠费 | 去平台检查 key 和余额 |
| `[错误] 找不到 data/chunks_v2` | 上游没跑 | 按顺序跑第 1~3 步 |
| `embedding-3` 报错 | 智谱接口变动 | 把 `p1_2_index.py` 里 `EMBED_MODEL` 改成 `embedding-2` |
| FAISS 的 `allow_dangerous_deserialization` 警告 | 官方安全要求 | 正常现象，自己的库自己加载 |
| 答案胡说 / 答的不是这份手册 | 向量库没跟着重建 | 重跑第 4 步；核对 `vectorstore/_manifest.json` 里的 `sources` |
| 脚本找不到文件 | 路径问题 | 所有新脚本都用 `Path(__file__).resolve().parents[N]` 锚定项目根，在任何目录下运行都可以 |

## 简历写法（项目描述参考）

> 基于 LangChain 的芯片数据手册 RAG 问答系统：用 PyMuPDF 从 PDF 中提取正文与表格，
> 做了页眉页脚剔除、跨页表格合并、合并单元格回填、表格标题坐标定位等清洗；
> 切块时给每块贴上"手册名 + 页码 + 章节路径/表格标题"的上下文前缀，
> 用智谱 embedding-3 向量化后存入 FAISS；用户提问时检索 top-k 片段注入 Prompt，
> 调用 DeepSeek 生成带页码溯源的回答；提供 FastAPI + 前端网页的交互界面。
