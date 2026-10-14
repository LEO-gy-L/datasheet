# -*- coding: utf-8 -*-
"""
文档（数据手册）业务
====================
这个文件只管**两件事**，而且都很快（毫秒级）：

    ① 磁盘上的 PDF 文件：落盘、删文件
    ② documents 表：新增一行、改状态、查列表

它**故意不碰**下面这些慢活：
    解析 PDF / 切块 / 调 embedding 向量化  ->  那是 indexing_service 的活
    往 FAISS 里加向量、删向量              ->  也是 indexing_service 的活

为什么要把"快"和"慢"分得这么干净：
    建库要几十秒到十几分钟，如果它的代码混在这里，那么"查一下列表"
    这种接口就可能因为不小心走到建库那条分支而卡住整个请求。
    现在这个文件里**没有任何一个函数会超过一秒**，读代码的人一眼就能确认。

⚠️ 两道安全护栏（都在这个文件里）：
    ① 文件名必须原样落盘在 DATASHEETS_DIR 下 —— 上传的文件名是**用户输入的**，
       直接拼路径会出路径穿越（传一个 "../../.env" 就把密钥文件覆盖了）。
       所以落盘前只取 basename，再做一次"最终路径必须在 DATASHEETS_DIR 里面"的校验。
    ② 一次只认 .pdf —— 见下面 ALLOWED_EXT 的说明。
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from backend.app.common.exceptions import ConflictError, NotFoundError
from backend.app.config import CHUNKS_DIR, DATASHEETS_DIR, STORE_DIR, TABLE_DIR, TEXT_DIR
from backend.app.models.document import (
    STATUS_FAILED,
    STATUS_INDEXED,
    STATUS_INDEXING,
    STATUS_UPLOADED,
    Document,
)
from backend.app.utils.time_fmt import fmt, now

# 允许上传的扩展名。
#
# ⚠️ 为什么只有 pdf，而不是页面上原来写的「.pdf / .txt / .md / .docx」
# ------------------------------------------------------------------
#   因为**后面那条流水线只认 PDF**：
#       ingestion/text.py    用 pymupdf 逐页抽文字
#       ingestion/tables.py  用 pymupdf 的 find_tables() 找表格
#       ingestion/chunking.py 里还有一段 build_figure_chunks 用 pymupdf 找矢量图
#   这三步全都直接吃 PDF。收下 .txt 的后果不是"不支持"，
#   而是**上传成功、建库失败** —— 用户以为传上去了，等半天收到一个
#   pymupdf 的报错，还得回头猜是怎么回事。
#
#   所以宁可上传这一步就说清楚"只要 PDF"（被挡下时立刻知道原因），
#   也不要先收下来再失败。等真的需要 txt/md 时，
#   正确做法是**再写一条纯文本的入库链路**，而不是往这条 PDF 流水线里塞。
ALLOWED_EXT = {"pdf"}

# 单文件大小上限：200 MB。
# 现有的手册最大 8 MB，留足余量；但必须有一个上限 ——
# 不然有人传个 2 GB 的文件进来，解析进程会被 OOM 杀掉，
# 而且磁盘会被悄悄占满（没有任何提示）。
MAX_UPLOAD_BYTES = 200 * 1024 * 1024


# ---------------------------------------------------------------- 落盘
def _safe_target(name: str) -> Path:
    """把用户传进来的文件名，安全地变成 DATASHEETS_DIR 下的一个路径。

    为什么不能直接 `DATASHEETS_DIR / name`：
        如果 name 是 "../../.env"，拼出来的路径就跑到项目根外面去了 ——
        这是经典的**路径穿越（path traversal）**漏洞。
        攻击者不需要什么高深技巧，用 curl 传一个带 ../ 的文件名就行。

    两层防护（都要有，各自能挡住不同的情况）：
        ① Path(name).name —— 只取最后一段，把任何目录部分丢掉。
           注意要同时处理 Windows 的反斜杠：Path("a\\b").name 在 Linux 上
           是 "a\\b"（反斜杠不是分隔符），所以这里手工再切一次。
        ② 拼好之后用 resolve() 展开成绝对路径，**再确认它确实在
           DATASHEETS_DIR 里面**。这一步是兜底：万一 ① 有哪个绕过的方式，
           这里一定拦得住。
    """
    # ① 剥掉任何目录成分（两种分隔符都处理）
    base = name.replace("\\", "/").split("/")[-1].strip()

    if not base or base in {".", ".."}:
        raise ConflictError("文件名不合法")

    target = (DATASHEETS_DIR / base).resolve()

    # ② 兜底校验：父目录必须正好是 DATASHEETS_DIR
    if target.parent != DATASHEETS_DIR.resolve():
        raise ConflictError("文件名不合法")

    return target


def _count_pages(path: Path) -> int:
    """数一下 PDF 有多少页。

    为什么在**上传**时就数，而不是等建库：
       建库可能失败，失败了也得知道这份手册有多少页（显示在列表里）。
       而且上传时数一次是毫秒级的（只是读文件尾部的页表），
       建库时再数一次属于重复劳动。

    为什么失败就返回 0 而不是抛异常：
       页数只是个展示字段。为了它让"上传"整个失败，代价太大 ——
       文档损坏这件事，等到建库那一步会得到更准确的报错。
    """
    try:
        import pymupdf
        with pymupdf.open(path) as doc:
            return len(doc)
    except Exception:      # noqa: BLE001 —— 见上面说明，页数不值得让上传失败
        return 0


def _store_chunk_counts() -> dict[str, int]:
    """从向量库的语料文件里统计"每份手册各自贡献了多少块"。

    为什么要读文件而不是查数据库：
        块的归属真相在 `vectorstore/docs.jsonl` 里（每行一个块，带 source 字段），
        数据库里那份是**副本**。副本可能因为"上次建库没更新统计"而过期，
        所以列表上显示的数字直接从真相处读。

    读不到文件（还没建过任何库）时返回空字典 —— 不算错误，
    表现为列表里所有行的块数都是 0，这是对的。
    """
    path = STORE_DIR / "docs.jsonl"
    counts: dict[str, int] = {}
    if not path.exists():
        return counts

    try:
        import json
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    src = json.loads(line).get("source", "")
                except ValueError:
                    continue        # 单行坏了就跳过，不要整份统计都拿不到
                if src:
                    counts[src] = counts.get(src, 0) + 1
    except OSError:
        return {}
    return counts


# ---------------------------------------------------------------- 查询
def sync_from_disk(db: Session) -> int:
    """把 datasheets/ 里**已经在磁盘上、但数据库里没有**的 PDF 补登记进表。

    为什么需要这个函数（不写会有个很尴尬的现象）：
        docs/backend_接入方案.md 里那批手册早在建库脚本时代就已经躺在
        datasheets/ 目录里了，而 documents 表是这次才建的、里面是空的。
        于是打开「入库」页会看到**一个空表格** —— 明明文件都在，
        页面却说"共 0 条"。用户第一反应是"我的文件呢？"

    为什么只补"数据库里没有的"，而不管已存在的：
        已经登记过的那些，状态是运行时状态（indexing / failed / 进度），
        磁盘扫描**看不出来**。拿磁盘推断出来的状态去覆盖，
        会把正在跑的任务状态冲掉 —— 属于"用一个不完整的信息源
        去覆盖一个完整的信息源"。所以这里只做"补漏"，不做"修正"。

    状态怎么推断（三种情况，都有明确证据，不猜）：
        向量库语料里有它的块  -> indexed（确实能检索到）
        有切块产物但没进向量库 -> uploaded（切过了但没建库，需要点建库）
        两者都没有            -> uploaded（新文件，同样需要点建库）
    """
    DATASHEETS_DIR.mkdir(parents=True, exist_ok=True)

    known = {stem for (stem,) in db.query(Document.stem).all()}
    store_counts = _store_chunk_counts()

    added = 0
    for pdf in sorted(DATASHEETS_DIR.glob("*.pdf")):
        stem = pdf.stem
        if stem in known:
            continue

        name = pdf.name
        if name in store_counts:
            status, chunks = STATUS_INDEXED, store_counts[name]
        else:
            status, chunks = STATUS_UPLOADED, 0

        db.add(Document(
            name=name,
            stem=stem,
            ext="pdf",
            size=pdf.stat().st_size,
            status=status,
            stage="",
            progress=100 if status == STATUS_INDEXED else 0,
            pages=_count_pages(pdf),
            chunks=chunks,
            indexed_at=now() if status == STATUS_INDEXED else None,
        ))
        added += 1

    if added:
        db.commit()
    return added


def list_docs(db: Session) -> list[dict]:
    """管理员「入库」页的列表：全部手册，按上传时间倒序。"""
    sync_from_disk(db)      # 先把磁盘上漏登记的补上，再查

    rows = db.query(Document).order_by(Document.created_at.desc(), Document.id.desc()).all()
    counts = _store_chunk_counts()
    return [_to_dict(r, counts) for r in rows]


def list_options(db: Session) -> list[dict]:
    """助理页 PDF 选择器：**只给已入库的**，按文件名排序。

    只给已入库的理由：选择器的语义是"只在这份手册里找答案"。
    如果把"未入库"的也列出来，用户选中它提问，检索会在这个 source 上
    一轮都命不中，最后答个"资料里没找到" —— 用户完全不知道
    是自己选了一份**根本没进库**的手册。不给选，就没有这个误会。
    """
    rows = (
        db.query(Document)
        .filter(Document.status == STATUS_INDEXED)
        .order_by(Document.name)
        .all()
    )
    counts = _store_chunk_counts()
    return [
        {
            "value": r.name,        # 就是向量库 metadata.source 里的值，直接传给 /api/ask
            "label": r.name,
            "chunks": counts.get(r.name, r.chunks or 0),
            "pages": r.pages or 0,
        }
        for r in rows
    ]


def get(db: Session, doc_id: int) -> Document:
    """按 id 取，取不到抛 404（业务异常，由全局处理器翻译成 HTTP 状态码）。"""
    row = db.get(Document, doc_id)
    if row is None:
        raise NotFoundError("文档不存在")
    return row


def get_by_stem(db: Session, stem: str) -> Document | None:
    return db.query(Document).filter(Document.stem == stem).first()


# ---------------------------------------------------------------- 新增
def create(db: Session, filename: str, data: bytes) -> Document:
    """把上传的文件存到磁盘，并在表里登记一行（状态 uploaded）。

    ⚠️ 校验顺序是有讲究的：**先校验、后落盘**。
       反过来（先存再检查）的话，一个超大的非法文件已经躺在磁盘上了，
       还得再写一段"回滚删除"的代码 —— 而且那段代码自己也可能失败，
       于是磁盘上留下一堆没人管的垃圾文件。
    """
    raw_name = filename or ""
    ext = raw_name.rsplit(".", 1)[-1].lower() if "." in raw_name else ""

    if ext not in ALLOWED_EXT:
        raise ConflictError("只支持 PDF 文件（当前入库流水线是围绕 PDF 做的）")

    if not data:
        raise ConflictError("文件是空的")

    if len(data) > MAX_UPLOAD_BYTES:
        raise ConflictError(f"文件超过 {MAX_UPLOAD_BYTES // 1024 // 1024} MB 上限")

    target = _safe_target(raw_name)
    stem = target.stem

    if db.query(Document).filter(Document.stem == stem).first() is not None:
        raise ConflictError(f"《{target.name}》已经在库里了，请先删除它再重新上传")

    # 磁盘上已经有同名文件但表里没有（比如手工拷进来的）—— 同样要挡住，
    # 否则下面的 write_bytes 会**静默覆盖**掉那个文件。
    if target.exists():
        raise ConflictError(f"datasheets/ 里已经有同名文件《{target.name}》，请先改名或删除")

    DATASHEETS_DIR.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)

    row = Document(
        name=target.name,
        stem=stem,
        ext=ext,
        size=len(data),
        status=STATUS_UPLOADED,
        stage="",
        progress=0,
        pages=_count_pages(target),
        chunks=0,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------- 删除
def delete(db: Session, doc: Document) -> None:
    """删除一份手册：数据库记录 + 磁盘 PDF + 三道中间产物目录。

    ⚠️ 为什么在建库进行中时必须拒绝（不能删）：
        建库是在**另一个线程**里跑的，它正在往 data/text_v2/<stem>/ 里写文件。
        这时候把目录删掉，那个线程会：
          ① 继续往一个已经不存在的目录写（有的库会自动重建，有的直接报错）
          ② 如果恰好删在"正在写"的那一刻，产物可能半新半旧
        最后表现为一份莫名其妙的 failed。更糟的是，
        **用户已经看到"已删除"了**，不会想到是这里出的问题。
        所以这里直接拒绝，让用户等十几秒再删。

    ⚠️ 为什么删目录要用固定路径拼接，而不是拿数据库里的字段拼：
        stem 是唯一约束值、且创建时已经过 _safe_target 校验，
        但"删除"是破坏性操作 —— 这里再确认一次它不含路径分隔符，
        成本几乎为零，收益是"永远不会删到 DATASHEETS_DIR 外面去"。
    """
    if doc.status == STATUS_INDEXING:
        raise ConflictError("这份手册正在建库，等它跑完再删")

    if "/" in doc.stem or "\\" in doc.stem or ".." in doc.stem:
        raise ConflictError("文档名异常，为安全起见拒绝删除")

    # ① 数据库记录
    db.delete(doc)
    db.commit()

    # ② 三道中间产物目录。
    #    用 shutil.rmtree 是必要的（目录里有很多文件），
    #    但**只删这三个我们自己的目录**，且路径前缀写死成 config 里的常量 ——
    #    这样即使 stem 被伪造，也只能删到 data/ 下面，碰不到别的地方。
    import shutil
    for base in (CHUNKS_DIR, TEXT_DIR, TABLE_DIR):
        d = base / doc.stem
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)

    # ③ 磁盘 PDF —— **留到最后删**。
    #    顺序是有意的，不是随手写的：调用方（api/documents.py）会先调
    #    indexing_service.remove_source()，而那一步要重建父块表 ——
    #    它读的是 data/chunks_v2/ 下的 parents.jsonl，不是这份 PDF。
    #    但"源文件最后删"是个更稳的通用习惯：万一前面某一步抛了异常，
    #    至少原始 PDF 还在，人工排查时还能重跑一遍建库。
    #    反过来先删 PDF 的话，剩下的一切都变成不可复现的了。
    pdf = DATASHEETS_DIR / f"{doc.stem}.pdf"
    if pdf.exists():
        pdf.unlink()


# ---------------------------------------------------------------- 状态流转
def set_state(
    db: Session,
    doc: Document,
    *,
    status: str | None = None,
    stage: str | None = None,
    progress: int | None = None,
    pages: int | None = None,
    chunks: int | None = None,
    error: str | None = None,
    touch_indexed_at: bool = False,
) -> None:
    """改一行状态。**所有字段都是"传了才改"**（None = 不动）。

    为什么用这种"只改传进来的字段"的写法：
        建库线程会在一分钟内调用它七八次（每个阶段开始/结束各一次）。
        如果每次都写全字段，就必须先读出来再原样填回去 ——
        中间只要有人误传一个 None，就把已有数据清掉了
        （典型的：把 pages 清成 0，列表上页数突然没了）。
        让 None 表示"不改"，就不会有这种误伤。

    ⚠️ commit 时机：本函数每次都 commit。
       代价是建库过程中多几次写盘（SQLite 写一次几毫秒，可忽略）；
       收益是**前端轮询能看到实时进度** —— 如果不 commit，
       另一个会话（HTTP 请求）读到的还是旧值，进度条就不动了。
    """
    if status is not None:
        doc.status = status
    if stage is not None:
        doc.stage = stage
    if progress is not None:
        doc.progress = progress
    if pages is not None:
        doc.pages = pages
    if chunks is not None:
        doc.chunks = chunks
    if error is not None:
        doc.error = error
    if touch_indexed_at:
        doc.indexed_at = now()

    doc.updated_at = now()      # onupdate 只在 UPDATE 时生效，显式写一次更直观
    db.commit()


# ---------------------------------------------------------------- 组装
def _to_dict(row: Document, counts: dict[str, int] | None = None) -> dict:
    """ORM -> 前端字典。

    字段名必须和前端 `frontend/src/api/docs.js` 里用的**逐字符一致**，
    这是"前端零改动"的前提（沿用 history/feedback 那两次的做法）。

    `indexed` 是 `status == "indexed"` 的投影，两个都给 ——
    理由见 schemas/document.py 里的说明。
    """
    counts = counts or {}
    return {
        "id": row.id,
        "name": row.name,
        "size": row.size or 0,
        "type": row.ext or "pdf",
        "indexed": row.status == STATUS_INDEXED,
        "status": row.status,
        "stage": row.stage or "",
        "progress": row.progress or 0,
        "pages": row.pages or 0,
        # 块数优先信任向量库语料的实际统计，退回数据库里那份记录
        "chunks": counts.get(row.name, row.chunks or 0),
        "error": row.error or "",
        "createdAt": fmt(row.created_at),
        "indexedAt": fmt(row.indexed_at) or None,
    }


__all__ = [
    "ALLOWED_EXT",
    "MAX_UPLOAD_BYTES",
    "STATUS_FAILED",
    "create",
    "delete",
    "get",
    "get_by_stem",
    "list_docs",
    "list_options",
    "set_state",
    "sync_from_disk",
]
