# -*- coding: utf-8 -*-
"""
文档（数据手册）管理接口
========================
    GET    /api/documents                    文档列表（管理员）
    POST   /api/documents/upload             上传 PDF（管理员，multipart）
    POST   /api/documents/{id}/index         触发建库（管理员，**立刻返回**）
    DELETE /api/documents/{id}               删除（管理员）
    GET    /api/documents/options            下拉选项（**任何登录用户**）

⚠️ 权限的两档，为什么只有 options 是普通的
--------------------------------------------------
    管理员那一档（列表 / 上传 / 建库 / 删除）会改动**整台服务器**：
        占磁盘、花 embedding 的钱、影响所有人的检索结果。
    普通用户那一档只需要**只读一个很短的下拉列表**：
        他要用助理页的"限定在这份手册里提问"，就得知道有哪些手册可选。

    把列表接口也放开给普通用户是不对的 —— 它会白白暴露
    "这台服务器上有哪些文件、哪些建库失败了、失败原因是什么"，
    这些都属于运维信息，不是用户该看的。

⚠️ 为什么所有返回都是 dict，不用 response_model
--------------------------------------------------
    沿用 history / feedback 那两次的做法（见 schemas/document.py 的说明）：
    字段名由 service 手工组装，好处是**一眼能看出返回给前端的到底是什么**，
    而不是先查 pydantic 怎么序列化、再回来对字段名。
    这个项目的前端是照着一份手写契约写的，字段一致性比"自动文档"重要。

⚠️ 为什么这个文件里也没有 try/except
--------------------------------------------------
    业务异常（文档不存在、正在建库、重名……）在 common/exceptions.py 里，
    由 main.py 的全局处理器统一翻译成 HTTP 状态码。
    接口层只负责"收参数 -> 调服务 -> 返回结果"。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.dependencies.auth import get_current_user, require_admin
from backend.app.models.user import User
from backend.app.services import document_service, indexing_service

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.get("")
def list_documents(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    """文档列表。

    注意 `admin` 这个变量在函数体里**没被用到** —— 它唯一的作用就是
    让 FastAPI 执行 require_admin 这个依赖（顺便触发权限检查）。
    写成 `_admin` 会更明白"我是故意的"，但 FastAPI 依赖注入只看参数名，
    下划线开头也一样能用，所以这里保留 admin 更好读。
    """
    return document_service.list_docs(db)


@router.get("/options")
def document_options(
    user: User = Depends(get_current_user),      # ← 只要登录，不要求管理员
    db: Session = Depends(get_db),
) -> list[dict]:
    """助理页 PDF 选择器的选项：只列**已入库**的手册。

    ⚠️ 这个接口必须注册在 /{doc_id} 之类的动态路由**之前**吗？
       本文件里没有 GET /{doc_id}，所以不存在"options 被当成 id 匹配掉"的问题。
       但将来如果加了 GET /{doc_id}，**必须**把它放到这个函数后面 ——
       FastAPI 是按声明顺序匹配的，"options" 会被 /{doc_id} 抢先吃掉，
       然后报一个 "int_parsing: 'options' is not a valid integer" 的怪错。
       这条注释就是留给那时候的自己的。
    """
    return document_service.list_options(db)


@router.get("/{doc_id}/progress")
def document_progress(
    doc_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """单份手册的建库进度。

    前端轮询用它，而不是反复拉整个列表：
        列表要顺带做一次磁盘扫描（sync_from_disk）和一次语料统计，
        每 2 秒跑一次有点浪费；进度查询只是一次主键查询。
    """
    doc = document_service.get(db, doc_id)
    return indexing_service.get_progress(db, doc)


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """上传一份 PDF（**只存文件，不建库**）。

    ⚠️ 上传和建库为什么是两个接口（这个设计很重要）
    --------------------------------------------------
        上传 = 把文件写到磁盘，毫秒级。
        建库 = 解析 + 切块 + 调几百次 embedding，几分钟，**而且花钱**。

        合成一个接口的话：
          ① 用户点一下要转圈好几分钟，中途断网就前功尽弃；
          ② 传错文件（比如传了一份不想要的）想删掉，
             但建库已经跑起来了，钱已经花了。

        拆开之后：上传完可以先看列表、可以攒几份一起建、
        可以先把传错的删掉 —— **在花钱之前**都有反悔的机会。

    ⚠️ 用 `await file.read()` 一次读进内存，而不是分块写盘
        200 MB 上限的文件读进内存是可以接受的（我们有明确的上限）。
        分块写盘那种写法（一边读一边写）在高并发下才真正需要，
        这个项目是单机、单人上传，不值得为它增加复杂度。
        **但上限必须存在** —— 没有上限的话，一个几 GB 的文件
        会把服务进程 OOM 掉，而且磁盘会被悄悄占满。

    ⚠️ filename 是**用户可控的输入**，不能直接拿去拼路径。
       具体怎么防路径穿越，见 document_service._safe_target()。
    """
    data = await file.read()
    doc = document_service.create(db, file.filename or "", data)
    return document_service._to_dict(doc)


@router.post("/{doc_id}/index")
def index_document(
    doc_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """触发建库。**立刻返回**，真正的活儿在后台线程里跑。

    这个接口正常情况下**一秒内**就返回了（连数据库查询一起）。
    前端拿到响应后不会再阻塞，改为每 2 秒来问一次进度
    （GET /api/documents/{id}/progress）。

    为什么这里要先把状态写成"排队中"再提交任务：
        提交任务和线程真正开始跑之间有几十毫秒。
        这几十毫秒内如果用户刷新页面，会看到这份手册还是"未入库"，
        于是再点一次 —— 虽然 indexing_service 里的锁会挡住第二次提交，
        但用户体验上"我明明点了，怎么没反应"。
        先把状态写下去，刷新就能看到"排队中"，行为是一致的。
    """
    doc = document_service.get(db, doc_id)

    # 提交任务。重复提交会抛 ConflictError -> 409（前端提示"正在建库"）
    indexing_service.submit(doc_id)

    return {"ok": True, "id": doc_id, "status": "indexing",
            "message": "已开始建库，可以离开这个页面，进度会自己更新"}


@router.delete("/{doc_id}")
def delete_document(
    doc_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """删除一份手册：文件 + 中间产物 + **向量库里的块**。

    ⚠️ 两件事分开做、都要做（顺序也是有意的）：
        ① remove_source  —— 摘掉向量库里的块（不花钱，用的还是原来那批向量）
        ② doc_service.delete —— 删记录 + 删磁盘文件

        为什么①在前：如果先删了文件再摘向量，中途失败的话，
        向量库里留着**一份源文件已经不存在的块**。检索命中它时，
        界面会显示一个"来自某份不存在的手册"的出处 —— 而且没人能再修它
        （源文件都没了，重建不出这批块）。
        反过来做，中途失败的最坏结果是"文件删了但向量还在"，
        这时重新点一次删除就能修好，是可恢复的。

    ⚠️ 建库进行中不能删（document_service.delete 里会拒绝）。
    """
    doc = document_service.get(db, doc_id)

    # 先挡住"正在建库"，再动向量库 —— 否则白跑一趟 remove_source
    if doc.status == "indexing" or indexing_service.is_running(doc_id):
        from backend.app.common.exceptions import ConflictError
        raise ConflictError("这份手册正在建库，等它跑完再删")

    stats = indexing_service.remove_source(doc.name, doc.stem)
    document_service.delete(db, doc)

    return {"ok": True, "removedChunks": stats["removed"]}
