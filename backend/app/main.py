# -*- coding: utf-8 -*-
"""
FastAPI 应用装配（后端启动点）
==============================
这是**整个后端的入口**。它只做"装配"，不写任何业务逻辑：

    创建 app -> 挂 CORS -> 挂全局异常映射 -> 注册路由 -> 启动时建表+预热引擎

启动方法（**必须在项目根目录**，模块路径是相对当前目录解析的）：

    python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
或者直接双击项目根目录的 start_backend.bat（里面就是上面这一行）。

启动后浏览器访问：
    http://127.0.0.1:8000/docs    自动生成的接口文档，可以直接点 "Try it out" 试
    http://127.0.0.1:8000/api/health   健康检查，网页用它判断后端有没有起来

⚠️ 访问根路径 http://127.0.0.1:8000/ 会返回 404 —— 这是正常的：
   没有定义 "/" 这个路由。这不是故障，是"这里本来就没东西"。
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.api import auth, documents, feedback, history, qa, users
from backend.app.common.exceptions import (
    AccountDisabledError,
    AuthError,
    ConflictError,
    EmptyQuestionError,
    ForbiddenError,
    IndexNotFoundError,
    ModelCallError,
    NotFoundError,
    RAGError,
)
from backend.app.config import API_TITLE, API_VERSION, CORS_ORIGINS
from backend.app.database import SessionLocal, init_db
from backend.app.services.indexing_service import shutdown_executor
from backend.app.services.rag_service import get_engine
from backend.app.services.user_service import seed_admin

# ---------------------------------------------------------------------------
# 业务异常 -> HTTP 状态码的映射表（全后端唯一一份）
# ---------------------------------------------------------------------------
# 为什么放在这里而不是每个路由里 try/except：
#   5 个路由文件 × 5 种异常 = 25 段一模一样的样板代码。集中一处映射，
#   路由函数就只剩"调服务 + 返回结果"，而不是被异常处理淹没。
#
# 用 dict 而不是 if/elif：这张表本身就是文档 —— 扫一眼就知道
# "哪类错误对应哪个状态码"，加新异常只要加一行。
#
# ⚠️ 查找用的是 isinstance（不是精确类型相等），所以顺序有意义：
#   如果将来出现继承关系（比如 SubAuthError(AuthError)），
#   父类必须排在子类**后面**，否则子类会先被父类的状态码截胡。
_ERROR_STATUS: dict[type[Exception], int] = {
    EmptyQuestionError: 400,      # 用户输入有问题
    AuthError: 401,               # 没登录 / 密码不对
    AccountDisabledError: 403,    # 账号被禁用
    ForbiddenError: 403,          # 没权限
    NotFoundError: 404,           # 东西不存在
    ConflictError: 409,           # 撞了（账号名重复、想禁用最后一个管理员）
    IndexNotFoundError: 500,      # 服务端没准备好（向量库缺）
    ModelCallError: 503,          # 上游模型不可用
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """服务生命周期钩子。

    yield 之前 = 开始接收请求之前：建表 -> 造种子管理员 -> 预热引擎。

    为什么建表放启动时（而不是手工跑一次脚本）：
        只要启动就保证表结构在，"clone 下来直接跑"就不会缺表。
        create_all 是幂等的（表已存在就跳过），重复启动没有副作用。

    为什么预热引擎放在这里，而不是等第一个请求来了再加载：
        **快速失败**。向量库不存在的话，启动阶段就直接报错退出，
        你能立刻看到红字；否则要等你问了第一个问题，才收到一句
        "没找到向量库"，还得去翻日志才知道是启动时的问题。

    yield 之后 = 服务关闭时。目前没有需要清理的资源（FAISS 是只读内存映射），
    以后接了数据库连接池、后台任务，清理逻辑写在这里。
    """
    init_db()

    # 用 with 打开会话：这个写法保证异常时也会关掉连接
    with SessionLocal() as db:
        seed_admin(db)

    get_engine()
    yield

    # ---- 关闭时的清理（2026-10-03 补上）----
    # 为什么这里现在真的需要写点东西了：
    #   建库用的是后台线程池（services/indexing_service.py）。不显式关它，
    #   进程退出时那些线程会被**直接掐断** —— 已经写了一半的
    #   vectorstore/docs.jsonl.tmp 会残留下来（虽然不影响检索，
    #   因为正式文件是靠"临时文件 + 原子改名"才生效的，但会留下垃圾文件）。
    #   cancel_futures=True 表示"排队中的任务别跑了"；
    #   wait=False 表示"不等正在跑的那个"—— 建库可能要几分钟，
    #   等它会让你按 Ctrl+C 之后卡住不动，还以为死机了。
    #
    # ⚠️ 代价要说清楚：正在跑的那个建库任务会被中断，
    #    它的状态会永远停在 "indexing"。重新启动后再点一次"重新入库"即可
    #    （状态可以在前端重新触发，不需要手工改数据库）。
    shutdown_executor()


app = FastAPI(title=API_TITLE, version=API_VERSION, lifespan=lifespan)


@app.exception_handler(RAGError)
async def business_error_handler(request: Request, exc: RAGError) -> JSONResponse:
    """把业务异常翻译成 HTTP 响应。

    响应体用 `{"detail": "..."}` —— 这是 FastAPI HTTPException 的原生格式，
    所以前端的 client.js 里那段错误解析逻辑（认 detail 字符串）不用改一行。

    兜底规则：映射表里找不到的异常给 400。
    为什么不给 500：能走到这里的都是 RAGError 的子类，
    也就是**我们主动抛出来的业务错误**，而不是程序崩了 ——
    业务错误基本都跟"这次请求的参数/状态不对"有关，400 更贴切。
    真正的程序崩溃不会走这个处理器，FastAPI 会自己返回 500。
    """
    status = next(
        (code for cls, code in _ERROR_STATUS.items() if isinstance(exc, cls)),
        400,
    )
    return JSONResponse(status_code=status, content={"detail": str(exc)})


# CORS（跨源资源共享）：
#   浏览器有个安全规则 —— 网页只能请求"同源"的接口。
#   前端跑在 5173、后端跑在 8000，端口不同就算跨源，不配这个白名单，
#   浏览器会直接拦掉请求并报 "blocked by CORS policy"（后端其实收到了，是浏览器不给看）。
#   白名单具体内容在 config.CORS_ORIGINS 里。
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    # Authorization 头是 2026-10-03 加登录后新增的：自定义请求头必须在白名单里，
    # 否则浏览器预检（OPTIONS）不通过，请求根本发不出去。
    # 用 ["*"] 就能覆盖它，不用逐个列。
    allow_headers=["*"],
)

# 把路由挂上来。每个 router 自带 "/api" 或 "/api/xxx" 前缀：
#   qa        GET  /api/health   POST /api/ask
#   auth      POST /api/auth/login   GET /api/auth/me   PUT /api/auth/password ...
#   users     GET  /api/users        PUT /api/users/{id}/password ...
#   history   GET  /api/history      DELETE /api/history/{id}
#   feedback  GET  /api/feedbacks    POST /api/feedbacks   PUT /api/feedbacks/{id}
#   documents GET  /api/documents    POST /api/documents/upload ...
#             GET  /api/documents/options  ← 唯一对普通用户开放的文档接口
#
# ⚠️ documents 必须放在**最后**：它内部有 /{doc_id}/progress 这样的动态路径段。
#    虽然它的前缀是 /api/documents，和上面的路由不会撞，
#    但保持"静态路径的 router 在前、带动态段的在后"这个顺序是个好习惯 ——
#    将来万一有人把前缀改成 /api，顺序错了就会出现"options 被当成 id"的怪问题。
app.include_router(qa.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(history.router)
app.include_router(feedback.router)
app.include_router(documents.router)
