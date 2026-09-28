# Datasheet RAG 智能问答系统

芯片数据手册智能问答：把 PDF/TXT 数据手册丢进 `datasheets/` 文件夹，
就能用自然语言提问（如"GPIO 最大输出电流多少"），系统检索原文后由 DeepSeek 生成答案，并给出来源。

技术栈：Python + LangChain + FAISS + 智谱 Embedding（免费）+ DeepSeek + Streamlit

## 目录结构

```
datasheet-rag/
├── .env                    ← 填你的两个 API Key（不要外传）
├── requirements.txt        ← 依赖清单
├── datasheets/             ← 数据手册放这里（已内置一份示例 WB32F）
├── vectorstore/            ← 向量库（运行 step3 后自动生成）
└── src/
    ├── api.py              ← 后端接口（网页版依赖它）
    ├── step1_llm.py        ← 第1步：验证 DeepSeek 能调通
    ├── step2_load_split.py ← 第2步：加载文档+切块
    ├── step3_vectorstore.py← 第3步：向量化存 FAISS（文档变了才重跑）
    ├── step4_rag.py        ← 第4步：命令行问答（核心）
    └── app.py              ← Streamlit 版界面（旧版，可不用）

web/
└── index.html            ← 自定义网页界面（推荐用这个，动画+渐变风格）

start_backend.bat         ← 双击启动后端服务
```

## 环境搭建（只需做一次）

在项目目录（datasheet-rag）下打开终端：

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

## 按顺序运行

```bash
# 第1步：验证模型能通（看到回复+token用量即成功）
.venv\Scripts\python src\step1_llm.py

# 第2步：看文档加载和切块效果
.venv\Scripts\python src\step2_load_split.py

# 第3步：建向量库（生成 vectorstore/index.faiss）
.venv\Scripts\python src\step3_vectorstore.py

# 第4步：开始问答！试试这些问题：
#   "GPIO 最大输出电流是多少？"
#   "待机功耗多少？支持哪些通信接口？"
#   "ADC 有几个通道？"（观察它怎么从原文找答案）
.venv\Scripts\python src\step4_rag.py

# 第5步（可选）：网页版
.venv\Scripts\python -m streamlit run src\app.py
```

## 推荐使用方式：自定义网页界面（前后端分离）

1. 双击项目根目录的 `start_backend.bat` → 会弹出一个黑窗口，显示 `Uvicorn running on http://127.0.0.1:8000`
2. 双击 `web/index.html` → 浏览器打开漂亮的聊天界面，右上角显示"后端已连接"即可提问
3. 用完关掉黑窗口即停止服务

> 架构说明：`src/api.py` 是后端（Python 干活），`web/index.html` 是前端（负责好看），
> 两者通过 HTTP 通信。这就是工业界的"前后端分离"，也是简历上能写的一条。

## 换成真实数据手册

把真实 PDF（如 STM32、ESP32 官方 datasheet）丢进 `datasheets/`，
重跑 step3，再跑 step4 即可。中英文手册都行。

## 常见问题

| 报错 | 原因 | 解决 |
|---|---|---|
| `请先在 .env 文件里填入...` | 密钥没填 | 编辑 .env |
| 401 / Unauthorized | 密钥错了或欠费 | 去平台检查 key 和余额 |
| `embedding-3` 报错 | 智谱接口变动 | 把代码里 model 改成 `embedding-2` |
| FAISS 的 `allow_dangerous_deserialization` 警告 | 官方安全要求 | 正常现象，自己的库自己加载 |
| 答案胡说 | 检索没命中 | chunk_size 调小（300），或 k 调大（6） |

## 简历写法（项目描述参考）

> 基于 LangChain 的芯片数据手册 RAG 问答系统：使用 RecursiveCharacterTextSplitter 对 PDF 数据手册切块，
> 通过 Embedding 模型向量化并存入 FAISS 向量库；用户提问时检索 top-k 相关片段注入 Prompt，
> 调用 DeepSeek 生成带出处溯源的回答；提供 Streamlit 交互界面。
