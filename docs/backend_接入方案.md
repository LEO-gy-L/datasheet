# 后端接入方案（数据库 + 真实数据）

> 目标：把前端所有"假信息"换成真数据 —— 账号密码、入库、问题历史、用户反馈全部落库。
> 状态：**设计稿，等确认后按 P1 → P5 分批落地**。
> 日期：2026-10-03

---

## 一、总览：数据落在哪

```
                     ┌─────────────────────────────────────────┐
                     │        SQLite  data/app.db              │
                     │                                         │
   登录 / 用户管理 ────┤  users        账号 + 角色 + 密码哈希      │
   信息页 / 改密码     │                                         │
                     │                                         │
   入库页 / PDF 选择 ──┤  documents    文件 + 建库状态 + 页数块数   │
                     │                                         │
   助理页每次提问 ────┤  qa_history   问题 + 答案 + 出处 + 归属人   │
   历史问答页         │                                         │
                     │                                         │
   反馈按钮 / 反馈页 ──┤  feedbacks    分类 + 说明 + 状态 + 回复     │
                     └─────────────────────────────────────────┘
                                        │
                            向量库 vectorstore/（不变）
                            FAISS 索引 + metadata.source 过滤
```

四张表，一个不变：**FAISS 向量库继续留在磁盘上**，数据库不存向量。原因见「决策 1」。

---

## 二、现状盘点

### 已经有的（不用重做）

| 东西 | 位置 | 状态 |
|---|---|---|
| 数据库连接层 | `backend/app/database.py` | 写好了，**只是没被 import** |
| SQLAlchemy | venv 已装 | OK |
| PyJWT 2.8.0 | venv 已装 | OK |
| python-multipart | venv 已装 | OK（文件上传必需） |
| `RAGEngine.ask(question, source=...)` | `services/rag_service.py:229` | **已支持按 PDF 过滤** |
| 接口路径约定 | `frontend/src/api/*.js` 里的【接后端后】注释 | 已经定好，照它写 |
| 空目录 | `models/` `schemas/` `dependencies/` | 已建好，等着填 |

### 是假的（要换掉）

| 东西 | 位置 | 假在哪 |
|---|---|---|
| 账号表 | `mock/data.js:23-38` | 密码**明文**写在前端，F12 直接可见 |
| 文档列表 | `mock/data.js:41-92` | 写死的 5 条 |
| 用户列表 | `mock/data.js:95-136` | 写死的 4 条 |
| 反馈列表 | `mock/data.js:149-199` | 写死的 4 条 |
| 改密码 / 改资料 | `api/auth.js:65-78` | 只做校验，`return delay({ok:true})` —— **什么也没存** |
| 上传 / 建库 / 删除文档 | `api/docs.js` | 全是 `delay()` 假成功 |
| 问答 | `api/chat.js` | **真的**，唯一真接口 |

---

## 三、数据库设计（4 张表）

### 3.1 `users` —— 账号（管理员和普通用户同一张表）

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER PK | 自增 |
| `username` | TEXT UNIQUE NOT NULL | 登录名 |
| `password_hash` | TEXT NOT NULL | 格式 `pbkdf2_sha256$轮数$盐$哈希`，**绝不存明文** |
| `name` | TEXT | 显示名（"管理员"、"小张"） |
| `email` | TEXT | |
| `role` | TEXT DEFAULT 'user' | `admin` \| `user` |
| `status` | TEXT DEFAULT 'active' | `active` \| `disabled` |
| `created_at` | DATETIME | |
| `last_login_at` | DATETIME | 登录成功时更新（用户管理页那个"最后登录"） |

> 为什么管理员不分表：字段完全一样、登录逻辑一样。分两张表以后每个查询都要判断两次，收益为零。靠 `role` 区分就够。

### 3.2 `documents` —— 文档与建库状态

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER PK | |
| `filename` | TEXT NOT NULL | 原始文件名。**必须与向量库里 metadata 的 `source` 完全一致** |
| `filesize` | INTEGER | 字节 |
| `filetype` | TEXT | `pdf` \| `txt` |
| `stored_path` | TEXT | 落盘路径（`datasheets/xxx.pdf`） |
| `status` | TEXT | `uploaded` \| `indexing` \| `indexed` \| `failed` |
| `error` | TEXT | 建库失败原因（成功时为空） |
| `pages` | INTEGER | 页数 |
| `chunks` | INTEGER | 切块数 |
| `uploaded_by` | INTEGER FK → users.id | 谁传的 |
| `created_at` | DATETIME | |
| `indexed_at` | DATETIME | 建库完成时间 |

> `status` 是前端轮询进度的唯一依据。四态对应界面四种显示：
> 未入库（灰）/ 建库中（转圈）/ 已入库（正常）/ 建库失败（红字 + 原因）。

### 3.3 `qa_history` —— 问答历史

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER PK | |
| `user_id` | INTEGER FK → users.id | 归属人（每个人的历史互相看不到） |
| `question` | TEXT NOT NULL | 用户问的 |
| `answer` | TEXT | 模型答的（markdown 原文） |
| `sources` | TEXT | JSON 字符串，存 `["xxx.pdf 第 37 页", ...]` |
| `source_doc` | TEXT | 当时选中的那份 PDF；`null` = 全部手册 |
| `seconds` | REAL | 耗时 |
| `conversation_id` | TEXT | **预留字段**，现在留空 |
| `created_at` | DATETIME | 历史页按它倒序 |

> 为什么存 `sources` 用 JSON 文本而不是独立表：它只是展示用的标签数组，从不需要按它查询。单开一张表要多一次 join，没收益。
> `conversation_id` 现在没用，是为了将来做"多轮对话"时**不用改表结构**。

### 3.4 `feedbacks` —— 用户反馈

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER PK | |
| `user_id` | INTEGER FK → users.id | 谁提的 |
| `category` | TEXT | 答案不准 / 检索不到 / 格式错乱 / 回答太慢 / 其他 |
| `content` | TEXT NOT NULL | 用户写的具体说明 |
| `question` | TEXT | 针对哪一轮提问（从助理页带过来） |
| `answer` | TEXT | 当时系统给的回答 |
| `status` | TEXT | `pending` \| `processing` \| `resolved` |
| `reply` | TEXT | 管理员回复 |
| `replied_by` | INTEGER FK → users.id | 谁回的 |
| `created_at` | DATETIME | |
| `replied_at` | DATETIME | |

> 表结构和 `mock/data.js` 里那份假数据**完全对齐**，所以前端页面代码不用改。

---

## 四、后端文件清单

### 新增

```
backend/app/
├── security/
│   ├── password.py          密码哈希与校验（标准库 pbkdf2，零新依赖）
│   └── token.py             JWT 签发与解析（PyJWT，已装）
├── models/
│   ├── user.py              users 表
│   ├── document.py          documents 表
│   ├── qa_history.py        qa_history 表
│   └── feedback.py          feedbacks 表
├── schemas/
│   ├── auth.py              LoginRequest / LoginResponse / ChangePasswordRequest ...
│   ├── user.py              UserOut / UserPatch ...
│   ├── document.py          DocumentOut / DocOption ...
│   ├── history.py           HistoryOut / HistoryQuery ...
│   └── feedback.py          FeedbackIn / FeedbackUpdate ...
├── services/
│   ├── auth_service.py      登录校验、改密码、改资料
│   ├── user_service.py      管理员查/改用户
│   ├── document_service.py  上传、建库调度、删库
│   ├── history_service.py   历史的增查删
│   └── feedback_service.py  反馈的增查改
├── api/
│   ├── auth.py              /api/auth/*
│   ├── users.py             /api/users/*
│   ├── documents.py         /api/documents/*
│   ├── history.py           /api/history/*
│   └── feedback.py          /api/feedbacks/*
├── dependencies/
│   └── auth.py              get_current_user / require_admin 两个依赖
├── tasks/
│   └── indexing.py          后台建库任务（P5 才用）
└── seed.py                  建表 + 首个管理员种子
```

### 改动

| 文件 | 改什么 |
|---|---|
| `main.py` | 挂 5 个新 router；`lifespan` 里加 `init_db()` + `seed_admin()` |
| `api/qa.py` | `/ask` 加 `source` 参数；答完把这一轮写进 `qa_history`（需要当前用户） |
| `config.py` | 加 `JWT_SECRET` / `TOKEN_EXPIRE_MINUTES` / `UPLOAD_DIR` |
| `models/__init__.py` | 汇总 import 四张表，否则 `create_all` 看不到它们 |
| `requirements.txt` | 补声明 `sqlalchemy` / `PyJWT` / `python-multipart`（**已经装了，只是没写进清单**） |

### 分层依赖方向（不许反过来）

```
api/        只认 HTTP 和 schema，异常映射成状态码
  ↓
services/   纯业务，不知道 HTTP 是什么
  ↓
models/     ORM 表定义
  ↓
database.py / security/
```

这套规矩沿用 `api/qa.py` 已经立的样板（业务异常在 service 抛，接口层翻译成 400/403/404/500）。

---

## 五、接口清单

### 认证 `/api/auth`

| 方法 | 路径 | 作用 | 谁能调 |
|---|---|---|---|
| POST | `/auth/login` | 换 token | 所有人 |
| GET | `/auth/me` | **新增**：拿当前用户（刷新页面恢复登录态） | 登录后 |
| POST | `/auth/logout` | 作废 token | 登录后 |
| PUT | `/auth/password` | 改自己的密码 | 登录后 |
| PUT | `/auth/profile` | 改自己的名字 / 邮箱 | 登录后 |

### 用户管理 `/api/users`（管理员）

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/users?keyword=` | 列表 + 模糊搜索 |
| PUT | `/users/{id}` | 改账号名 / 名字 / 邮箱 |
| PUT | `/users/{id}/password` | **重置密码**（就是"忘记密码"那条通道） |
| PUT | `/users/{id}/status` | 启用 / 禁用 |

### 文档 `/api/documents`

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/documents` | 列表（入库页表格） |
| GET | `/documents/options` | **新增**：助理页 PDF 下拉只列已入库的 |
| POST | `/documents/upload` | 上传（multipart/form-data），**不建库** |
| POST | `/documents/{id}/index` | 触发建库，**立刻返回**，后台跑 |
| GET | `/documents/{id}/status` | **新增**：轮询进度 |
| DELETE | `/documents/{id}` | 删文件 + 清对应向量块 |

### 历史 `/api/history`

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/history?keyword=&limit=&offset=` | 自己的历史，倒序，可搜问题关键词 |
| GET | `/history/{id}` | 单条详情 |
| DELETE | `/history/{id}` | 删单条 |
| DELETE | `/history` | 清空自己的 |

### 反馈 `/api/feedbacks`

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/feedbacks?status=` | 用户侧只看自己的；管理员看全部 |
| POST | `/feedbacks` | 提交 |
| PUT | `/feedbacks/{id}` | 管理员回复 / 改状态 |

### 问答 `/api/ask`（改造）

```
POST /api/ask
body: { "question": "...", "source": "STM32F103C8_Datasheet.pdf" }   ← source 是新增的
```

行为变化：答完自动写一行 `qa_history`。**落库失败不能影响回答**（用 try/except 兜住，日志记一下就行）。

---

## 六、前端改动清单

### 新增

| 文件 | 作用 |
|---|---|
| `src/api/history.js` | 历史接口 |
| `src/views/user/History.jsx` | 历史问答页 |
| `src/components/DocPicker.jsx` | 助理页的 PDF 选择器 |

### 改动

| 文件 | 改什么 |
|---|---|
| `src/menu.jsx` | 用户菜单在「用户信息」**前面**插入一条：`{ key: "/history", label: "历史问答" }` |
| `src/App.jsx` | 加 `<Route path="/history" element={<History />} />` |
| `src/views/user/Assistant.jsx` | 输入栏上方加 `<DocPicker>`；提问时把选中的 PDF 传给 `ask()` |
| `src/api/chat.js` | `ask(question, { source, signal })` |
| `src/api/auth.js` | mock → `request()`，删掉 `ACCOUNTS` 依赖 |
| `src/api/users.js` | mock → `request()` |
| `src/api/docs.js` | mock → `request()`，建库改轮询 |
| `src/api/feedback.js` | mock → `request()` |
| `src/context/AuthContext.jsx` | 启动时拿 token 调 `/auth/me`；token 失效自动踢回登录页 |
| `src/views/Login.jsx` | **删掉两个"一键填充演示账号"按钮** |
| `src/api/client.js` | 支持 FormData（有 FormData 时不要设 Content-Type） |
| `src/mock/data.js` | **删除**（`delay()` 挪到 `src/utils/`） |

### 侧栏最终的词条顺序（用户侧）

```
1. datasheet 助理   /assistant
2. 问题反馈         /feedback
3. 历史问答         /history      ← 新增
4. 用户信息         /profile
```

---

## 七、依赖：几乎不用装

| 包 | 状态 | 用途 |
|---|---|---|
| SQLAlchemy | ✅ 已装 | ORM |
| PyJWT 2.8.0 | ✅ 已装 | 签发 / 校验 token |
| python-multipart | ✅ 已装 | 文件上传 |
| bcrypt / passlib | ❌ 没装 | **不装了**，用标准库 `hashlib.pbkdf2_hmac` 代替 |
| 后台任务 | —— | 用标准库 `concurrent.futures`，不引 Celery |

> ⚠️ 这个 venv 是 **uv** 建的，**没有 pip**（`python -m pip` 会报 No module named pip）。
> 以后真要装包，用：`uv pip install --python .venv/Scripts/python.exe <包名>`
> 或者先修好：`.venv/Scripts/python.exe -m ensurepip`

---

## 八、四个关键技术决策（要你拍板）

### 决策 1：一个向量库，靠 source 过滤（推荐）

**不**给每份 PDF 建一个独立索引，而是**继续用一个 FAISS 索引**，检索时用 `metadata.source` 过滤。

- 支持这样做的事实：`RAGEngine.ask(question, source="xxx.pdf")` 已经实现了
- 好处：启动只加载一次；内存不翻倍；"跨手册对比"这类问题以后也好做
- 代价：暂时不能"同时在三份手册里搜"（要的话改成 `source in [...]` 即可）

### 决策 2：建库跑在线程池里（推荐）

管理员点"建库" → 接口立刻返回 → 线程池后台跑 → 状态写 `documents.status` → 前端每 2 秒轮询。

- 好处：零新依赖，不用装 Redis
- 代价：服务重启时正在跑的任务会丢，状态停在 `indexing`，需要手动再点一次
- 备选：Celery + Redis（生产级，本地开发太重，不建议现在做）

### 决策 3：密码哈希用标准库 pbkdf2（推荐）

- `hashlib.pbkdf2_hmac('sha256', password, salt, 200_000)` + 随机盐
- 好处：**零新依赖**（这个 venv 没 pip，装 bcrypt 要多绕一步）
- 安全性：Django 默认就用它，够用
- 备选：修好 pip 后装 bcrypt

### 决策 4：管理员不分表 + 历史一轮一行

- 管理员和普通用户同一张 `users` 表，靠 `role` 区分
- 历史记录：一次问答 = 一行（不做"会话分组"），但预留 `conversation_id`

---

## 九、五期实施顺序与验收标准

| 期 | 内容 | 验收标准（怎么算做完） |
|---|---|---|
| **P1** | 数据库地基 + 登录打通 | ① `admin / admin123` 能真登录 ② F12 里 localStorage 只有 token、没有密码 ③ 刷新页面不掉线 ④ 手改 token 会被拒 |
| **P2** | 用户管理 + 信息页 + 改密码 | ① 管理员能改 zhang 的密码，改完能用新密码登录 ② 能禁用账号，禁用后登录被拒 ③ 用户能改自己的名字 |
| **P3** | 问答历史 | ① 问一句 → 历史页能看到 ② 刷新不丢 ③ 能按关键词搜 ④ 能删单条 |
| **P4** | 问题反馈真数据 | ① 用户提交 → 管理员页看到 ② 管理员回复 → 用户页看到 ③ 状态能流转 |
| **P5** | 文档入库 + PDF 选择器 | ① 上传 PDF → 列表出现"未入库" ② 点建库 → 状态 indexing → indexed ③ 助理页下拉里出现它 ④ 选中后提问，答案只来自这份手册 |

先做 P1 的原因：**它是所有后续功能的地基**（其他接口全要"当前用户"这个依赖），而且链路最短 —— 数据库 → 哈希 → JWT → 一个接口 → 前端换一行调用。

P5 放最后的原因：**它最慢、最容易卡**（建库要调智谱 embedding，几百个块要几十秒到几分钟，还花钱），不适合拿来开局。

---

## 十、安全提醒（顺手要做的三件事）

1. **`.env` 加 `JWT_SECRET`**：随机长字符串。泄露了别人就能伪造任意用户的 token
2. **`.env` 已在 .gitignore 里**：新增的 secret 也绝不能提交
3. **`data/app.db` 要进 .gitignore**：里面是真实密码哈希和用户数据

---

## 十一、待确认清单

- [ ] 决策 1：单一向量库 + source 过滤 —— 同意吗？
- [ ] 决策 2：线程池后台建库 —— 同意吗？
- [ ] 决策 3：pbkdf2 标准库哈希 —— 同意吗？（还是先修 pip 装 bcrypt）
- [ ] 决策 4：管理员同表 + 历史一轮一行 —— 同意吗？
- [ ] 侧栏词条名："历史问答" 还是 "历史"？
- [ ] P1 是否现在开始？

---

## 十二、落地记录（2026-10-03 夜）

**结论**：用户说「你直接改代码」→ **P1 ~ P4 全部落地，P5 未做**。
开工前打了快照 `6a158a0`（回滚用 `git reset --hard 80394bd`），业务代码尚未提交。

### 12.1 已完成

| 期 | 内容 | 主要落地文件 |
|---|---|---|
| **P1** | 数据库地基 + 登录打通 | `security/password.py`、`security/token.py`、`models/user.py`、`dependencies/auth.py`、`services/auth_service.py`、`services/user_service.py`、`api/auth.py`、`schemas/auth.py`、`utils/time_fmt.py`、`main.py`（挂路由 + 全局异常处理器 + lifespan 建表种子） |
| **P2** | 用户管理 + 信息页 + 改密码 | `api/users.py`、`schemas/user.py`、前端 `api/users.js`、`api/auth.js` |
| **P3** | 问答历史 | `models/qa_history.py`、`services/history_service.py`、`api/history.py`、`api/qa.py`（答完落库）、前端 `api/history.js`、`views/user/History.jsx`、`menu.jsx`（新词条）、`App.jsx`（新路由） |
| **P4** | 问题反馈真数据 | `models/feedback.py`、`services/feedback_service.py`、`api/feedback.py`、前端 `api/feedback.js` |

顺带清理：`mock/data.js` 里的 `ACCOUNTS`（**明文密码**）/ `USERS` / `FEEDBACKS` 三份假数据已删除；
`Login.jsx` 底部的「演示账号一键填充」区块已删除；`Assistant.jsx` 的 markdown 渲染抽到 `utils/markdown.js`。

### 12.2 和设计稿不一致的 5 处（都是取舍，不是遗漏）

1. **出参不用 `response_model`**，改由 service 手工组装 dict。
   为的是字段名能与 `mock/data.js` 逐字符对齐（驼峰 `createdAt` / `lastLogin`），前端页面零改动。
2. **业务异常 -> 状态码用全局处理器**（`main.py` 的 `business_error_handler`），
   而不是每个路由写 `try/except`。5 个路由 × 5 种异常 = 25 段样板代码，改一处漏一处。
   只有 `/api/ask` 保留显式 try/except（它要区分三种模型相关的错误）。
3. **`mock/data.js` 没删**，因为入库页（`api/docs.js`）还在用它 —— 它属于 P5。
   但里面**只剩 `DOCUMENTS`**，敏感的和没用的都清掉了。
4. **管理员侧栏没有「历史问答」** —— 只加在普通用户侧栏（按需求原话"在用户左边加词条"）。
   管理员要看自己在助理页问过什么，暂时没有入口（遗留项）。
5. **新增了两个设计稿里没提的文件**：`utils/time_fmt.py`（统一 `2026-10-03 22:57` 这种格式）、
   `utils/markdown.js`（助理页和历史页共用同一套 sanitize，避免两处各写一份）。

### 12.3 验证结果

**后端（TestClient，23 项全过）**，重点几条：
- 无 token / 伪造 token / 密码错 → 401；普通用户调 `/users` → 403
- **前端传 `username: "伪造的"`，服务端存的是 token 里的 `zhang`** —— 身份伪造被挡住
- 改自己密码用错旧密码 → 401；管理员重置别人的密码不需要旧密码 → 200
- 禁用自己 → 409；禁用最后一个管理员 → 409；被禁用账号登录 → 403
- 管理员看不到别人的历史（`/history` 只按 token 过滤）

**前端（puppeteer 驱动 Edge，两轮）**：
- 登录页演示账号区块已消失、侧栏词条顺序为「助理 → 反馈 → 历史问答 → 用户信息」
- 账号管理显示数据库里的真实用户；反馈抽屉能看到用户的完整描述和管理员回复
- **真实提问一次 → 历史条数 1 → 2，新记录出现在列表** （P3 的核心闭环）
- 全程控制台零报错；`npm run build` 通过

### 12.4 怎么跑

```
双击 start_backend.bat                    # 后端 127.0.0.1:8000
cd frontend && npm run dev                # 前端 localhost:5173
```

默认账号：`admin / admin123`（首次启动自动创建）、`zhang / 123456`（测试时手动建的）。
数据库文件：`data/app.db`（44KB，已在 .gitignore 里）。
改初始管理员密码：在 `.env` 里加 `ADMIN_INIT_PASSWORD=xxx` —— ⚠️ **只对全新的空库生效**，
`admin` 已经存在时 `seed_admin()` 会直接跳过。

### 12.5 遗留（下一轮）

1. **P5：文档入库 + PDF 选择器**（用户明确提过）—— 涉及 documents 表、上传接口、
   后台建库任务 + 轮询进度、`client.js` 的 FormData 支持（**已提前写好**）、助理页的下拉选择器
2. **JWT 没有强制下线能力** —— 改密码后旧 token 仍然有效到过期（12 小时）。
   要做得加一张"已登出 token"表
3. **管理员看自己的历史**没有入口
4. `client.js` 的 401 广播已就位，但没做"提示一句再跳登录页"的交互


---

## 十三、P5 落地记录：文档入库 + PDF 选择器（2026-10-03 深夜）

**结论**：用户说「做」→ **P5 完成**。至此前端**零 mock**，`frontend/src/mock/` 目录已删除。
第 12.5 节列的遗留 1、4 已清，2、3 仍在。

### 13.1 新增文件

| 层 | 文件 | 职责 |
|---|---|---|
| 模型 | `models/document.py` | documents 表；status 四态 + stem 唯一 + STAGES/STAGE_PROGRESS 常量 |
| 契约 | `schemas/document.py` | `DocumentOut` / `DocOptionOut`（字段名的单一出处） |
| 服务 | `services/document_service.py` | **只做快活**：落盘、列表、删除、磁盘同步、状态流转。无一个函数超过一秒 |
| 服务 | `services/indexing_service.py` | **只做慢活**：四道工序编排、线程池、FAISS 增量写入/摘除、引擎重置 |
| 接口 | `api/documents.py` | 6 个端点（见 13.3） |

改动（少量、append 为主）：`models/__init__.py`（加 import）、`config.py`（加 TEXT_DIR/TABLE_DIR/CHUNKS_DIR）、
`main.py`（挂路由 + lifespan 关线程池）、`retrieval/hybrid.py`（**追加** `reset_retriever()`）、
`services/rag_service.py`（**追加** `reset_engine()`）。

前端：`api/docs.js`（换真接口）、`components/DocPicker.jsx`（新）、`views/admin/Ingest.jsx`（重写）、
`views/user/Assistant.jsx`（挂选择器 + 传 source）、`assets/css/assistant.css`（加选择器样式）、
**删除 `mock/data.js`**（`git rm`，想恢复：`git checkout HEAD -- frontend/src/mock/data.js`）。

### 13.2 四道工序

```
datasheets/<stem>.pdf
   │
   ├─① backend.app.ingestion.text      ──► data/text_v2/<stem>/page_XXXX.md      （子进程）
   ├─② backend.app.ingestion.tables    ──► data/tables_v5/<stem>/page_XXXX.md    （子进程）
   ├─③ backend.app.ingestion.chunking  ──► data/chunks_v2/<stem>/chunks.jsonl    （子进程）
   └─④ indexing_service._merge_store   ──► vectorstore/                          （本进程）
```

- **前 ③ 道走子进程**：pymupdf 解析一本 300 页手册峰值能吃几百 MB，且畸形 PDF 可能**段错误**
  （不是抛异常，是整个进程死）。子进程让内存随进程退出归还，崩溃也只影响那一个子进程。
- **第 ④ 道留在本进程**：它的原料是 FAISS 对象，跨进程会引入"子进程改了、主进程不知道"的复杂度。
- **线程池 `max_workers=1`**：`vectorstore/index.faiss` 是共享文件，两个任务并行会出现
  "A 读 115 → B 读 115 → A 存 315 → B 存 265，A 的 200 个凭空消失"的丢失更新，且不报错。

### 13.3 接口清单

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/documents` | 管理员 | 列表；顺带做磁盘同步（见 13.4） |
| GET | `/api/documents/options` | **登录即可** | 下拉项，**只给已入库的** |
| GET | `/api/documents/{id}/progress` | 管理员 | 轮询用，只查主键，比拉列表轻 |
| POST | `/api/documents/upload` | 管理员 | multipart，**只存文件不建库**，毫秒级 |
| POST | `/api/documents/{id}/index` | 管理员 | **立刻返回**（实测 5ms），活儿在后台 |
| DELETE | `/api/documents/{id}` | 管理员 | 摘向量库 + 删文件 + 删中间产物 |

**只有 `/options` 对普通用户开放**，理由：用户要用"限定在某份手册里提问"就得知道有哪些手册；
但"服务器上有哪些文件、哪份建库失败了、原因是什么"属于运维信息。

### 13.4 增量而非全量（这是"省钱 + 省时间"的关键）

`indexer.py` 默认把**全部手册**重新向量化一遍。库里有 115 块时再传一份新的，
全量重建会把那 115 块再送一遍 embedding 接口 —— **已经付过的钱再付一次**。
（钱其实不多，但**时间**很贵：1849 块 ≈ 232 批 × 1.5s 间隔 ≈ 6~15 分钟。）

所以第 ④ 步改成增量：`load_local` → 只对新块调 embedding → `add_embeddings` 追加 → `save_local`。
**FAISS 本身就是现成的向量缓存**，不需要再单独存一份向量文件。
删除同理：`delete(ids)` 用的还是那批已付款的向量，只是把其中一部分扔掉 —— **删除不花钱**。

⚠️ 增量必须同时维护两份东西，缺一不可：
`vectorstore/index.faiss`（能算相似度）和 `vectorstore/docs.jsonl`（块长什么样、来自哪一页）。
检索层启动时会自检两者数量是否相等（`hybrid.py` 里 `n_vec != len(self.chunks)`），
不等就**整体停用语义路** —— 症状是"库建好了，问什么都说找不到"。

### 13.5 踩到的坑（都可复用）

| 坑 | 现象 | 正解 |
|---|---|---|
| **库里存的键不是块 id** | `indexer.py` 调 `FAISS.from_embeddings()` **没传 `ids`**，FAISS 自己生成 uuid4 当键。按块 id 删一个都匹配不上 → 库从 115 变 230 | **按 `metadata.source` 删**（语义上本来就该这样，且不依赖键长什么样）。末尾那道数量自检拦下了污染 |
| `FAISS.delete()` 的语义 | 给的 id 必须**都存在**，否则抛 `ValueError`。用 `in existing` 过滤后变成空列表 → 一声不吭什么都没删 | 先按 source 扫描出真实存在的键，再删 |
| 这个版本的 `InMemoryDocstore` **没有 `mget`** | `AttributeError` | `_safe_mget()` 降级成逐条 `search()`，且自己兜异常 —— 删不掉只是留垃圾，不能让它把建库搞失败 |
| 建库后引擎不重置 | 后台显示"已入库"，但**提问搜不到新手册**（内存里的 FAISS 还是旧的） | `reset_engine()` + `reset_retriever()` **两个都要重置** |
| 上传文件名是用户输入 | `../../.env` 就能覆盖密钥文件 | `_safe_target()`：剥掉目录成分 + `resolve()` 后确认父目录就是 `datasheets/` |
| `sys.executable` 不能写死 `python` | 服务用 venv 启动，PATH 里那个 python 没装 pymupdf | 子进程命令一律用 `sys.executable -m 模块名`，`cwd=ROOT` |
| 线程池里的异常没人接 | 任务无声无息没了，状态永远停在 `indexing` | `_run_safely()` 兜住一切写进 `error` 字段；`_running` 集合的清理放 `finally` |
| 磁盘同步会覆盖运行态 | 拿磁盘推断的状态去覆盖数据库，把正在跑的 `indexing` 冲掉 | `sync_from_disk` **只补漏、不修正** |

### 13.6 实测数据（本机，CH32F103 29 页 / 115 块）

| 阶段 | 耗时 |
|---|---|
| ① 解析正文 | ~19 s |
| ② 解析表格 | ~47 s |
| ③ 切块 | ~2 s |
| ④ 向量化入库（15 批） | ~31 s |
| **合计** | **~97 s** |

进度权重的设定依据就在这张表：向量化占了约 1/3 的墙钟时间，
但批数多、每批都在动，所以要给它 50% 的进度区间（`STAGE_PROGRESS`），
否则进度条会卡在中段很久，看着像死了。

### 13.7 验证结果

**后端**（TestClient）：未登录 `/documents` → 401；普通用户 `/documents` → 403、`/options` → 200；
`/documents/9999/*` → 404。

**端到端**（打真实运行的 8000 端口）：
- 触发接口 **5 ms 返回**，后台进度真实推进：`0% 准备中` → `15% ① 完成` → `30% ②` →
  `50% ④ 中…` → `53% 1/15 批` → … → `100% indexed`
- 建完**立刻**提问 `CH32F103C6T6 的引脚数` → 答 `48 引脚`，出处 3 条 —— 证明引擎重置生效
- 库一致性：`index.faiss 115 向量 == docs.jsonl 115 块`，语义路 `vectorstore is not None`

### 13.8 仍然遗留

1. **JWT 没有强制下线能力** —— 改密码后旧 token 有效到过期（12 小时）
2. **管理员侧栏没有「历史问答」入口**
3. 只支持 `.pdf` —— 因为整套流水线建立在 pymupdf 上。要支持 txt/md 得**另写一条纯文本链路**，
   而不是往 PDF 流水线里塞（收了却建不了库，比当场拒收更糟）
4. `data/app.db` 里的 `zhang / 123456` 是测试时手工建的，正式部署应删
5. 建库任务被服务重启打断时，状态会停在 `indexing` —— 前端重新点一次即可，但**没有自动化的"孤儿任务回收"**
