# -*- coding: utf-8 -*-
"""
建库编排（把一份 PDF 变成能被检索到的东西）
============================================
这是 P5 里唯一"重"的文件，也是整个功能的核心。它干的事就一句话：

    把一份刚上传的 PDF，依次送过四道工序，最后落进向量库。

四道工序（顺序固定，不能换）：

    ① 正文   ingestion.text      PDF -> data/text_v2/<stem>/page_XXXX.md
    ② 表格   ingestion.tables    PDF -> data/tables_v5/<stem>/page_XXXX.md
    ③ 切块   ingestion.chunking  上两步的产物 -> data/chunks_v2/<stem>/chunks.jsonl
    ④ 入库   本文件 + FAISS       chunks.jsonl -> vectorstore/

为什么前 ③ 道用**子进程**跑（subprocess），而不是直接调它们的函数
------------------------------------------------------------------
这三个模块本来就是按"命令行工具"写的（各自有 main() 和 argparse），
而且它们干的活有很强的副作用：读整个 PDF、在内存里堆出几百个中间对象、
写几十上百个小文件。直接 import 进服务进程调，有两个实际麻烦：

    ① 内存不会还。pymupdf 解析一本 300 页的手册，峰值能吃掉几百 MB，
       析构之后 Python 也不一定马上把内存还给操作系统。跑几次之后，
       服务进程就变成一个占着 1 GB 的关键字 —— 而它平时只需要几十 MB。
    ② 崩了就一起崩。pymupdf 遇到畸形 PDF 是可能直接段错误的（不是抛异常，
       是**整个进程死掉**）。同一个进程里做，连带把整个后端服务带走。

子进程把这两件事都解决了：内存随进程退出归还，崩溃只影响那一个子进程，
服务照常在，还能把子进程的报错原文抓回来存进数据库。

⚠️ 为什么 ④ 老老实实留在**本进程**里做（这是唯一的例外）
------------------------------------------------------------------
因为它的原料是 FAISS 对象。FAISS 的索引在子进程里加载、修改、存盘之后，
本进程内存里那个检索器**不会自动知道** —— 要靠 reload 才行。
绕这一圈的复杂度，比"内存占用"这个代价大得多。而且第 ④ 步的原料
（一堆字符串）本身不重，真正重的向量计算在智谱的服务端。
所以留在这里，配一个线程池就够。

⚠️ 为什么用 max_workers=1
------------------------------------------------------------------
向量库是**一份共享的文件**（vectorstore/index.faiss）。
两个建库任务并行跑的话，会出现这个经典的丢失更新：

    任务 A 读入 index.faiss（115 个向量）
    任务 B 读入 index.faiss（115 个向量）   ← 读到的是同一份
    A 加上自己的 200 个，存盘 -> 315
    B 加上自己的 150 个，存盘 -> 265       ← A 那 200 个凭空消失

而且两边都不报错。串行化（一个跑完再跑下一个）是这里唯一简单又正确的做法 ——
反正建库是低频操作，用户也不会同时点两个。

⚠️ 增量而不是全量（这是"省钱"的关键）
------------------------------------------------------------------
indexer.py 的默认行为是**把全部手册重新向量化一遍**。
对这次的功能来说这不可接受：库里已经有 CH32F103 的 115 块，
再传一份新手册，全量重建会把那 115 块**重新送一遍 embedding 接口**——
一笔已经付过的钱，再付一次。

所以第 ④ 步改成增量：
    打开现有的 FAISS  ->  只对**新的块**调 embedding  ->  add_embeddings 追加  ->  存盘
已经付过钱的向量就躺在 index.faiss 里，FAISS 本身就是**现成的向量缓存**，
不需要再单独存一份。

⚠️ 增量必须同时维护两份东西，缺一不可
------------------------------------------------------------------
    vectorstore/index.faiss   向量（"能算相似度"）
    vectorstore/docs.jsonl    语料（"块长什么样、来自哪一页"）

检索层启动时会**自检两者数量是否相等**（retrieval/hybrid.py 里那段
`n_vec != len(self.chunks)` 的判断），不等就停用语义路。
所以本文件里每一次追加/删除，都严格保持这两份同步 ——
见 `_merge_store()` 完成之后的 assert。
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from backend.app.common.exceptions import ConflictError
from backend.app.config import CHUNKS_DIR, ROOT, STORE_DIR
from backend.app.database import SessionLocal
from backend.app.models.document import (
    STAGE_PROGRESS,
    STAGES,
    STATUS_FAILED,
    STATUS_INDEXED,
    STATUS_INDEXING,
    STATUS_UPLOADED,
)
from backend.app.services import document_service

# ---------------------------------------------------------------- 调参
# 子进程超时（秒）。给得很宽松，因为一本几百页的手册解析+切块确实要几分钟。
# 它的作用是兜住"卡死"（进程 hang 住不退出），不是"限制正常耗时"。
# 定太小会把正常的大文件误杀；定太大则卡死时要等很久才发现。
SUBPROCESS_TIMEOUT = 60 * 30          # 30 分钟

# 单个子进程最多留多少行输出进错误信息。
# 报错时子进程的 stdout 里往往有真正的原因（"第 7 页解析失败：..."），
# 但全存进去会撑爆数据库字段，所以只留**最后的** 30 行 ——
# 按经验，关键信息总在最后几行。
TAIL_LINES = 30


def _log(msg: str) -> None:
    """打一行带时间戳的日志。

    为什么不用 logging：
        整个项目现在都是 print（见 indexer.py / hybrid.py），
        这里刻意保持一致 —— 混用两套日志的话，你在终端里会看到
        "有的行有前缀、有的没有"，反而更难对时间线。
    """
    print(f"[建库 {datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ==================================================================
# 一、线程池：同一时刻只跑一个建库任务
# ==================================================================
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="indexing")

# 正在跑的任务的 doc_id 集合。
#
# 为什么光靠数据库的 status 判断不够，还要这么一个集合：
#    status 是"上一个阶段写进数据库的"，而提交任务是**立刻**发生的 ——
#    从"接口收到请求"到"线程真的开始跑、写下 status=indexing"之间有几十毫秒。
#    这几十毫秒内如果用户手快点了两下"重新入库"，
#    两次检查都会看到旧的 status（uploaded），于是排进两个任务。
#    这个锁 + 集合是同步的、立即生效的，正好补上这个窗口。
_lock = threading.Lock()
_running: set[int] = set()


def is_running(doc_id: int) -> bool:
    with _lock:
        return doc_id in _running


# ==================================================================
# 二、对外入口
# ==================================================================
def submit(doc_id: int) -> None:
    """提交一个建库任务。**立刻返回**，不等它跑完。

    为什么必须异步（不能用同步接口等它跑完）：
        建库要几十秒到十几分钟。同步接口的话：
          ① 浏览器会一直转圈，用户以为卡死了，然后刷新/关页面；
          ② 一旦连接断掉（切个标签、锁屏、网络抖动），
             请求被取消，后端那个任务就变成了"没人知道它在跑"；
          ③ 网关/反向代理通常几十秒就超时断开，压根等不到结果。
        所以正确的形态是：**接口立刻回一句"已开始"，真正的活儿在后台跑，
        前端定时来问"跑到哪了"**（就是下面 get_progress 提供的东西）。
    """
    with _lock:
        if doc_id in _running:
            raise ConflictError("这份手册正在建库，请等它跑完")
        _running.add(doc_id)

    _executor.submit(_run_safely, doc_id)
    _log(f"已提交建库任务 doc_id={doc_id}")


def _run_safely(doc_id: int) -> None:
    """线程池里的真正入口。

    分开写一层 `_run_safely` 而不是直接把 `_run` 交给线程池，是因为
    **线程池里的异常不会有人接**：`_run` 抛出来的异常会静静地躺在
    Future 对象里，没人去看（我们也没保存这个 Future），
    表现为"任务无声无息地没了，状态永远停在 indexing"。

    所以：任何异常都必须在这里被抓住、写进数据库的 error 字段。
    最后的 finally 负责把 _running 里的记录清掉 —— 放在 finally 里，
    是为了保证"即使写数据库本身也失败了"，这个名额仍然会被释放；
    否则一次意外会让这份手册**永远**没法再建库（每次都说"正在建库"）。
    """
    try:
        _run(doc_id)
    except Exception as e:      # noqa: BLE001 —— 后台线程必须兜住一切，见上面说明
        _log(f"doc_id={doc_id} 建库失败：{type(e).__name__}: {e}")
        _mark_failed(doc_id, f"{type(e).__name__}: {e}")
    finally:
        with _lock:
            _running.discard(doc_id)


def get_progress(db, doc) -> dict:
    """给轮询接口用的一小块数据（比整个文档对象轻）。"""
    return {
        "id": doc.id,
        "status": doc.status,
        "stage": doc.stage or "",
        "progress": doc.progress or 0,
        "chunks": doc.chunks or 0,
        "pages": doc.pages or 0,
        "error": doc.error or "",
    }


def shutdown_executor() -> None:
    """服务关闭时调一次（main.py 的 lifespan 在 yield 之后调）。

    为什么必须显式关：
        线程池里的线程默认不是守护线程。不关的话，Python 退出时会**等**它们跑完 ——
        建库要几分钟，表现为"按了 Ctrl+C，终端卡住半天没反应"，
        很容易让人以为进程死锁了，然后再开一个终端强杀。

    cancel_futures=True  排队中还没开始跑的任务直接取消（它们没做任何事，取消耗费为零）
    wait=False           不等正在跑的那个 —— 正在跑的是子进程调用，
                         我们没办法优雅地中断它，只能随它去
                         （它写完自己的临时文件才落盘，所以不会留下半个坏文件）
    """
    _executor.shutdown(wait=False, cancel_futures=True)
    _log("建库线程池已关闭")


# ==================================================================
# 三、四道工序
# ==================================================================
def _run_stage(module: str, args: list[str], label: str) -> str:
    """跑一个命令行阶段，返回它的 stdout（尾部若干行）。

    三个必须写在命令里的东西，以及为什么：

        sys.executable
            当前进程用的那个 python。**不能写死 "python"** ——
            服务是用 .venv/Scripts/python.exe 启动的，而 PATH 里那个 python
            可能是系统 Python，没装 pymupdf/faiss。写死就等着 ModuleNotFoundError。

        cwd=ROOT
            三个模块都是按"相对项目根目录"解释路径的（见 config.py 里把
            相对路径统一锚到 ROOT 的那几段）。工作目录不对，它们会
            找不到 PDF、也找不到上一次的产物。

        -m backend.app.ingestion.xxx
            用模块方式调用，而不是文件路径 —— 这样模块内的
            `from backend.app.config import ROOT` 这类绝对导入才有效。

    为什么不 `shell=True` 直接拼一个字符串命令：
        拼字符串就要处理引号和空格（Windows 上路径带空格太常见了），
        而且 shell=True 会把文件名里的特殊字符交给 shell 解释 ——
        我们的 stem 来自用户上传的文件名，这是个真实的风险。
        用列表形式传参（shell=False），参数不经过 shell，天然安全。
    """
    cmd = [sys.executable, "-m", module, *args]
    _log(f"{label} 开始：{' '.join(cmd[1:])}")

    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",       # 子进程输出里混进非 UTF-8 字节时别炸，替换掉即可
        timeout=SUBPROCESS_TIMEOUT,
    )

    out = (proc.stdout or "") + (proc.stderr or "")
    tail = "\n".join(out.strip().splitlines()[-TAIL_LINES:])

    if proc.returncode != 0:
        # 把**原文**带回上层。三个模块内部都有中文的错误提示
        # （"找不到 PDF"、"请先运行 xxx"），直接展示给用户比我们
        # 自己编一句话有用得多 —— 我们并不知道它到底卡在哪。
        raise RuntimeError(f"{label}失败（退出码 {proc.returncode}）：\n{tail}")

    _log(f"{label} 完成")
    return tail


def _stage_args(stem: str, pdf_rel: str) -> dict[str, list[str]]:
    """四个阶段各自的命令行参数。

    抽成一个小函数，是为了让"参数长什么样"只有一处 ——
    改一个参数名（比如 --out-dir 改名）时，不会漏改某一步。

    pdf_rel 是**相对项目根**的路径（如 "datasheets/xxx.pdf"），
    因为三个模块都是按这个约定解释 --pdf 的。
    """
    return {
        "text": ["--pdf", pdf_rel],
        "tables": ["--pdf", pdf_rel],
        "chunking": ["--pdf", pdf_rel],
    }


def _run(doc_id: int) -> None:
    """真正的建库流程。跑在后台线程里，所以自带一个数据库会话。"""
    # ⚠️ 后台线程**必须自己开一个数据库会话**。
    #    FastAPI 的 get_db() 依赖是绑在请求生命周期上的，请求一返回就 close 了，
    #    这个线程才刚开始跑 —— 拿那个会话用会报 "Session is closed"。
    db = SessionLocal()
    try:
        doc = document_service.get(db, doc_id)
        stem, name = doc.stem, doc.name

        document_service.set_state(
            db, doc, status=STATUS_INDEXING, stage="准备中…",
            progress=0, error="",
        )
        _log(f"开始为《{name}》建库（stem={stem}）")

        pdf = ROOT / "datasheets" / f"{stem}.pdf"
        if not pdf.exists():
            raise RuntimeError(f"找不到源文件 datasheets/{stem}.pdf")

        # ---- ①②③ 三道子进程工序 ----
        # 按 STAGES 里的顺序跑。前三个是子进程，第四个在主进程里做。
        for key, label in STAGES:
            if key == "indexing":
                break

            # ⚠️ "中…" 写在**跑之前**，进度写在**跑完之后**。
            #    反过来的话（跑完再改成"完成"），那 47 秒的表格解析期间，
            #    界面一直停在"① 解析正文 完成"上 —— 用户看着会以为卡住了。
            #    现在任何时刻显示的都是"正在做的那件事"。
            document_service.set_state(db, doc, stage=f"{label} 中…")
            stage_args = _stage_args(stem, f"datasheets/{stem}.pdf")
            _run_stage(
                f"backend.app.ingestion.{key}",
                stage_args[key],
                label,
            )
            document_service.set_state(db, doc, progress=STAGE_PROGRESS[key])

            # 每跑完一步就顺手刷新一下统计，前端能看到"块数"一点点长出来
            if key == "chunking":
                n = _count_chunk_lines(stem)
                document_service.set_state(db, doc, chunks=n)

        # ---- ④ 向量化入库（本进程，增量）----
        label = dict(STAGES)["indexing"]
        document_service.set_state(db, doc, stage=f"{label} 中…", progress=STAGE_PROGRESS["chunking"])

        def on_batch(done: int, total: int) -> None:
            """向量化过程中的进度回调：把 50% -> 100% 这一段摊开。

            为什么要摊开：这四步里它占了**一半以上的时间**。
            只报"④ 开始 -> ④ 结束"的话，进度条会卡在 50% 好几分钟，
            用户会以为死了。摊开之后至少能看到它在动。
            """
            base = STAGE_PROGRESS["chunking"]
            span = STAGE_PROGRESS["indexing"] - base
            pct = base + int(span * done / max(total, 1))
            # 这里直接在**同一个会话**里改对象再 commit，不走 set_state ——
            # 因为 on_batch 会被高频调用（每批一次），
            # 每次都重新走一遍字段判断没必要。反正 doc 就是这个会话里的对象。
            doc.stage = f"{label} {done}/{total} 批"
            doc.progress = min(pct, 99)     # 99 封顶，100 留给"真正完成"
            db.commit()

        stats = _merge_store(stem, name, on_batch=on_batch)

        document_service.set_state(
            db, doc,
            status=STATUS_INDEXED,
            stage="",
            progress=100,
            # ⚠️ 这里必须是 stats["added"]（**这份手册**切出多少块），
            #    不是 stats["chunks_in_store"]（**整个库**有多少向量）。
            #    这两个值在多手册并存时会差很远 —— 实测踩过：
            #    库里 CH32F103(115) + ESP32(226) = 341，
            #    重跑 CH32F103 时把 341 写进了它的 chunks 字段，
            #    /progress 接口就报"这份手册有 341 块"。
            #    列表页没露馅是因为它优先读语料统计（_to_dict 里
            #    `counts.get(row.name, ...)`），把库里那份错误记录盖住了 ——
            #    典型的"显示对了但数据错了"，不改迟早会在别处冒出来。
            chunks=stats["added"],
            touch_indexed_at=True,
        )
        _log(f"《{name}》建库完成：新增 {stats['added']} 块，库里共 {stats['chunks_in_store']} 块")

    finally:
        db.close()

    # ---- 让新内容立刻能被检索到 ----
    # ⚠️ 这一步**不能省**。检索器是个进程内单例（retrieval/hybrid.py 末尾的
    #    get_retriever），它在服务启动时就把 docs.jsonl 和 index.faiss
    #    读进内存了。刚才存到磁盘的新向量，那个单例**完全不知道** ——
    #    不重置的话，表现是"建库成功了，但怎么问都搜不到新手册"。
    #    放在 try 外面、db 关掉之后做，是因为重置和数据库无关。
    _reload_engine()


# ==================================================================
# 四、增量写入向量库
# ==================================================================
def _count_chunk_lines(stem: str) -> int:
    """数一下某个 stem 切出了多少块（一行一块）。"""
    path = CHUNKS_DIR / stem / "chunks.jsonl"
    if not path.exists():
        return 0
    n = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                n += 1
    return n


def _read_docs_jsonl() -> list[dict]:
    """读现有语料。行格式必须和 ingestion/indexer.py 写出来的完全一致，
    否则检索层（hybrid.load_chunks）会读不到字段 —— 而且不报错，只是字段变空。"""
    path = STORE_DIR / "docs.jsonl"
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue        # 坏行跳过，不让一行的格式问题毁掉整份语料
    return rows


def _write_docs_jsonl(rows: list[dict]) -> None:
    """整份重写语料。

    为什么整份重写而不是"追加"：
        重跑同一份手册时，旧块必须**先剔掉**再写新的（否则同一份手册
        会出现两代内容，检索时一半是旧版、一半是新版，而且 id 还重了）。
        整份重写把"剔除旧的 + 写入新的"合成一次原子操作 ——
        文件要么是旧的，要么是新的，不会出现写了一半的状态。
        语料就几百 KB，重写一遍是毫秒级的，不值得为它做增量。
    """
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    path = STORE_DIR / "docs.jsonl"
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    # 先写临时文件再改名：改名在文件系统里是**原子**的。
    # 直接原地写的话，写到一半进程被打断，语料就废了 ——
    # 而检索层下次启动会读到半份语料，表现为"有些手册怎么都搜不到"。
    tmp.replace(path)


def _evict_from_store(vs, source_name: str, also_ids: list[str] | None = None) -> int:
    """从 FAISS 里删掉某份手册的所有条目，返回删掉的条数。

    ⚠️ 为什么按 `metadata.source` 删，而不是按块 id 删
    ------------------------------------------------------------------
    这是 P5 实测踩出来的一个真坑，值得记下来：

        最初我用"块 id"来删（`r["id"] in existing`），结果一次都没匹配上 ——
        日志里连"已移除旧块"那行都没打印。
        原因是**库里存的键根本不是我们的块 id**：

            ingestion/indexer.py 里那句
                FAISS.from_embeddings(text_embeddings, embedding, metadatas)
            只传了 metadatas，**没传 ids**。
            于是 FAISS 自己给每条生成一个 uuid4 当键。

        所以库里躺着的是 "3f9c1b2e-..." 这种键，拿
        "CH32F103_Datasheet_CN_c0001" 去删，当然找不到 ——
        而且 `FAISS.delete()` 的语义是"给的 id 必须都存在，否则抛异常"，
        我用 `in existing` 过滤之后变成了**空列表**，
        于是它一声不吭什么都没删，后面 `add_embeddings` 又追加了 115 个 ——
        库从 115 变成 230，,然后被末尾的数量自检拦下（那道 assert 救了这次）。

    为什么改成按 source 删是对的（不只是"能用"）：
        我们要表达的语义本来就是"**把这份手册贡献的块全部摘掉**"，
        不是"删掉这 115 个 id"。按 source 删直接对应这个语义，
        而且**不关心键是 uuid 还是块 id** —— 两代数据统一处理。
        这是把"实现细节（键长什么样）"和"业务意图（删哪份手册）"解耦。

    为什么还要一个 also_ids 参数：
        兜极端情况 —— 万一哪次运行被中断，留下一条**不在**
        index_to_docstore_id 里（因此按 source 扫不到）但键正好等于
        我们要新写入的 id 的残留。langchain 的 add_embeddings 遇到重复键
        会抛 ValueError，那时报错信息很难指向真正的原因。
        先顺手清一遍，省得以后来查。
    """
    if vs is None:
        return 0

    keys = list(vs.index_to_docstore_id.values())
    if not keys:
        return 0

    # 用 mget 批量取（一次调用），而不是逐条 search ——
    # 库里上千块时，逐条 search 是上千次字典查找 + 异常开销。
    docs = _safe_mget(vs, keys)

    stale = [
        k for k, d in zip(keys, docs)
        if d is not None and (d.metadata or {}).get("source") == source_name
    ]

    if also_ids:
        seen = set(stale)
        stale.extend(i for i in also_ids if i in keys and i not in seen)

    if not stale:
        return 0

    vs.delete(stale)
    return len(stale)


def _safe_mget(vs, keys: list[str]) -> list:
    """批量取 docstore 里的文档，取不到的位置填 None。

    为什么要包一层：
        langchain_community 在不同版本里给 docstore 换过实现
        （InMemoryDocstore / 别的）。mget 是主流实现都有的方法，
        但万一将来换了一个没有它的实现，**这里降级成逐条 search** 也不能崩 ——
        删不掉旧块只是"库里多了些垃圾"，而这一层抛异常会让整个建库失败。
    """
    if hasattr(vs.docstore, "mget"):
        try:
            return list(vs.docstore.mget(keys))
        except Exception:      # noqa: BLE001 —— 见上面说明，降级即可
            pass

    out = []
    for k in keys:
        try:
            out.append(vs.docstore.search(k))
        except Exception:      # noqa: BLE001
            out.append(None)
    return out


def _embed_batched(texts: list[str], embeddings, on_batch=None) -> list[list[float]]:
    """分批向量化，带限流重试。

    这段的逻辑几乎是 indexer.py 里 build_index 的原样复刻，
    连参数都从那边 import 过来（见下面）—— 不是偷懒，是**故意只留一处调参**：
    batch 大小、重试次数、批间间隔这三个值，是当初实测调出来的
    （见 indexer.py 文件头那段"实测记录"）。这里要是自己再拍一组数，
    将来只管了一处、另一处忘了改，症状是"命令行建库很稳、网页建库老是失败"，
    极难查。
    """
    # 从 indexer 引入调参常量 —— 保证 CLI 和网页两条路径用同一组值
    from backend.app.ingestion.indexer import (
        BATCH_INTERVAL,
        BATCH_SIZE,
        EMBED_RETRIES,
        EMBED_RETRY_WAIT,
    )

    vectors: list[list[float]] = []
    total = -(-len(texts) // BATCH_SIZE)        # 向上取整 = (a + b - 1) // b

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        batch_no = i // BATCH_SIZE + 1

        emb: list[list[float]] | None = None
        for attempt in range(EMBED_RETRIES):
            try:
                emb = embeddings.embed_documents(batch)
                break
            except Exception as e:      # noqa: BLE001
                if attempt == EMBED_RETRIES - 1:
                    # 试到底还是不行 -> 抛出去，让整个建库标记为 failed。
                    # 为什么不吞掉继续下一批：那会建出一个**残缺的库** ——
                    # 检索时表现为"某些内容怎么都搜不到"，而且看不出是哪一批丢的。
                    # 宁可整份失败、用户重试，也不要留一个看起来正常却少东西的库。
                    raise
                wait = EMBED_RETRY_WAIT * (2 ** attempt)
                _log(f"  第 {batch_no}/{total} 批被拒（{type(e).__name__}），"
                     f"{wait:.0f}s 后重试")
                time.sleep(wait)

        if emb is None:                 # 理论上到不了这里（上面要么赋值要么抛）
            raise RuntimeError(f"第 {batch_no} 批向量化没有得到结果")
        vectors.extend(emb)

        if batch_no < total:
            time.sleep(BATCH_INTERVAL)  # 批间喘口气，降低被限流的概率
        if on_batch:
            on_batch(batch_no, total)

    return vectors


def _merge_store(stem: str, source_name: str, on_batch=None) -> dict:
    """把某个 stem 的切块结果**增量**合进向量库。

    这是本文件最核心的一段，每一步都对应一个具体的坑：

        ① 读新块（只读这一个 stem）—— 别的 stem 的块不重读，更不重新向量化
        ② 读现有语料，按 source 分成"要保留的"和"要被替换的"
        ③ 打开现有 FAISS（没有就新建），先把旧的删掉，再追加新的
        ④ 存盘，然后**校验两份数据的数量是否相等**（不等就抛，绝不放过）
        ⑤ 重写语料、合并父块表、更新清单

    返回一份统计，给日志和数据库用。
    """
    from langchain_community.vectorstores import FAISS

    from backend.app.ingestion.indexer import load_chunks
    from backend.app.retrieval.embeddings import get_embeddings

    # ---- ① 读新块 ----
    # load_chunks 是从 indexer.py 借来的，它顺带做了一件重要的事：
    # 把超长的索引文本按行截断（clip_index_text）。自己写一遍容易漏掉它，
    # 漏掉的后果是某一块超过 embedding 接口的 token 上限 ->
    # 整批 400 -> 整份手册建库失败，而且报错信息完全指不到是"哪一块太长"。
    docs, stats = load_chunks(CHUNKS_DIR, stem)
    if not docs:
        raise RuntimeError(
            f"{stem} 一块都没切出来。常见原因：PDF 是扫描版（没有文字层），"
            f"或页面全是图片。请确认 data/chunks_v2/{stem}/chunks.jsonl 有内容。"
        )

    texts = [d.page_content for d in docs]
    metadatas = [d.metadata for d in docs]
    ids = [d.metadata["id"] for d in docs]

    # ---- ② 现有语料按 source 分家 ----
    rows = _read_docs_jsonl()
    # 要被替换掉的旧行：**按文件名匹配**，不是按 stem。
    # 用 name（带 .pdf）是因为 metadata.source 存的就是它，两处必须对齐。
    old_rows = [r for r in rows if r.get("source") == source_name]
    keep_rows = [r for r in rows if r.get("source") != source_name]

    # ---- ③ 打开 / 新建向量库 ----
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    embeddings = get_embeddings()
    faiss_file = STORE_DIR / "index.faiss"

    if faiss_file.exists():
        vs = FAISS.load_local(
            str(STORE_DIR), embeddings,
            allow_dangerous_deserialization=True,   # 我们自己的库，理由同 hybrid.py
        )
        _log(f"已加载现有向量库：{vs.index.ntotal} 个向量")

        # 先把这份手册的旧块全部摘掉 —— 这一步是"重跑同一份手册"能正确工作的关键。
        # 不删的话，同一个知识点会在库里出现**两代**，检索时命中哪一代全看运气；
        # 而且 id 若相同还会让 add_embeddings 直接抛异常。
        #
        # ⚠️ 按 source 删（不是按 id）—— 原因见 _evict_from_store 的详细说明，
        #    简单说：库里旧的键是 FAISS 自己生成的 uuid，根本对不上我们的块 id。
        removed = _evict_from_store(vs, source_name, also_ids=ids)
        if removed:
            _log(f"已从向量库移除旧块 {removed} 个")
        else:
            _log("库里没有这份手册的旧块（首次入库）")

        vectors = _embed_batched(texts, embeddings, on_batch=on_batch)
        vs.add_embeddings(
            list(zip(texts, vectors)),
            metadatas=metadatas,
            ids=ids,
        )
    else:
        # 第一次建库：库里什么都没有，直接全新建。
        _log("向量库还不存在，这次是全新创建")
        vectors = _embed_batched(texts, embeddings, on_batch=on_batch)
        vs = FAISS.from_embeddings(
            text_embeddings=list(zip(texts, vectors)),
            embedding=embeddings,
            metadatas=metadatas,
            ids=ids,
        )

    vs.save_local(str(STORE_DIR))

    # ---- ④ 写语料 + 数量自检 ----
    new_rows = keep_rows + [
        {
            "id": d.metadata["id"],
            "index_text": d.page_content,       # 建 BM25 用的文本
            "content": d.metadata["content"],   # 原文，命中后展示
            "source": d.metadata["source"],
            "type": d.metadata["type"],
            "title": d.metadata["title"],
            "page_start": d.metadata["page_start"],
            "page_end": d.metadata["page_end"],
            "parent_id": d.metadata.get("parent_id", ""),
        }
        for d in docs
    ]
    _write_docs_jsonl(new_rows)

    # ⚠️ 这道 assert 是**故意**留着的，不是写着好看。
    #    检索层会检查"向量数 == 块数"，不等就整体停用语义路
    #    （见 retrieval/hybrid.py 的 n_vec != len(self.chunks)）。
    #    真出现不等，症状是"库建好了，但问什么都说找不到" ——
    #    极难定位。与其让用户去猜，不如在这里当场炸掉、报错写进数据库。
    n_vec = vs.index.ntotal
    if n_vec != len(new_rows):
        raise RuntimeError(
            f"向量库与语料对不上：index.faiss {n_vec} 个向量 vs docs.jsonl "
            f"{len(new_rows)} 块。检索会整体失效，已中止。"
        )

    # ---- ⑤ 父块表 + 清单 ----
    n_parents = _rebuild_parents()
    _write_manifest(new_rows, n_parents)

    return {
        "added": len(docs),
        "replaced": len(old_rows),
        "chunks_in_store": n_vec,
        "parents": n_parents,
        "clipped": stats.get("clipped", 0),
    }


def _rebuild_parents() -> int:
    """把**所有** stem 的 parents.jsonl 合并成一份 parents.json。

    为什么每次都要全量合并（而不是只把自己那份追加进去）：
        删除一份手册时，它的父块必须跟着消失。只做追加的话，
        父块表会越攒越多，里面躺着已经删掉的手册的整节原文 ——
        检索命中时会把一份**已经不存在的资料**送进 prompt 里当依据。
        全量合并不贵（就是读几十个小文件的每一行），胜在永远和现状一致。
    """
    parents: dict[str, dict] = {}
    if CHUNKS_DIR.exists():
        for stem_dir in sorted(p for p in CHUNKS_DIR.iterdir() if p.is_dir()):
            pf = stem_dir / "parents.jsonl"
            if not pf.exists():
                continue
            for line in pf.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        item = json.loads(line)
                        parents[item["parent_id"]] = item
                    except (ValueError, KeyError):
                        continue

    STORE_DIR.mkdir(parents=True, exist_ok=True)
    (STORE_DIR / "parents.json").write_text(
        json.dumps(parents, ensure_ascii=False), encoding="utf-8")
    return len(parents)


def _write_manifest(rows: list[dict], n_parents: int) -> None:
    """更新建库清单。**格式和 indexer.py 写的那份保持一致** ——
    这里只是多加了两个字段（built_by / updated_at），
    因为"这份库是谁建的"在有了网页入口之后变得重要了。

    为什么 embedding_model 从 config 取而不是写死字符串：
        这个字段是给人排错用的。嵌入式模型一旦被换掉、
        而这里还印着老模型名，就变成一条**误导人的线索** ——
        排查的人会确信"库是 embedding-3 建的"，然后往错的方向想很久。
        （换模型必须重建全库这条铁律，见 retrieval/embeddings.py 的说明。）
    """
    from backend.app.config import EMBED_MODEL

    by_source: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for r in rows:
        s = r.get("source", "")
        by_source[s] = by_source.get(s, 0) + 1
        t = r.get("type", "text")
        by_type[t] = by_type.get(t, 0) + 1

    manifest = {
        "built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "incremental",          # 和 CLI 的 full / bm25-only 区分开
        "embedding_model": f"zhipuai/{EMBED_MODEL}",
        "n_docs": len(rows),
        "n_text": by_type.get("text", 0),
        "n_table": by_type.get("table", 0),
        "n_figure": by_type.get("figure", 0),
        "n_parents": n_parents,
        "sources": by_source,
        "built_by": "web:/api/documents/{id}/index",
        "note": "由网页端增量维护；命令行全量重建请用 "
                "python -m backend.app.ingestion.indexer",
    }
    (STORE_DIR / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


# ==================================================================
# 五、从向量库移除一份手册（删除文档时调用）
# ==================================================================
def remove_source(source_name: str, stem: str) -> dict:
    """把一份手册贡献的块从向量库里摘干净。

    ⚠️ 这是**真正让"删除"生效**的一步。
       只删磁盘上的 PDF 是不够的：PDF 删了，那 115 个块还在
       vectorstore 里躺着，检索照样命中，模型照样拿它当依据回答 ——
       你会看到"我已经删掉的手册，答案里还在引用它"。

    三件事都要做，缺一不可：
        ① FAISS 里的向量        -> vs.delete(ids)
        ② docs.jsonl 里的语料行  -> 整份重写（按 source 过滤掉）
        ③ parents.json 的父块    -> 全量重建（会自动少掉它那份）

    这个操作**不花钱**（用的还是已经付过钱的向量，只是把其中一部分扔掉），
    所以删除可以做得很快。
    """
    from langchain_community.vectorstores import FAISS

    from backend.app.retrieval.embeddings import get_embeddings

    result = {"removed": 0, "chunks_in_store": 0}

    rows = _read_docs_jsonl()
    gone = [r for r in rows if r.get("source") == source_name]
    keep = [r for r in rows if r.get("source") != source_name]

    if not gone and not rows:
        return result     # 还没建过库，没什么可摘的

    # ---- ① 删向量 ----
    faiss_file = STORE_DIR / "index.faiss"
    if faiss_file.exists():
        vs = FAISS.load_local(
            str(STORE_DIR), get_embeddings(),
            allow_dangerous_deserialization=True,
        )
        # 同样按 source 删 —— 和 _merge_store 走同一个函数，
        # 保证"重新建库"和"删除文档"两条路径摘东西的方式完全一致。
        removed = _evict_from_store(vs, source_name)
        if removed:
            vs.save_local(str(STORE_DIR))
        result["removed"] = removed
        result["chunks_in_store"] = vs.index.ntotal
        _log(f"已从向量库移除《{source_name}》的 {removed} 个块")

    # ---- ② 写语料 ----
    _write_docs_jsonl(keep)

    # ---- ③ 重建父块表（它会自动少掉这份手册贡献的那些父块）----
    n_parents = _rebuild_parents()
    _write_manifest(keep, n_parents)

    # ---- ④ 让检索器重新加载 ----
    _reload_engine()
    return result


# ==================================================================
# 六、重置引擎单例
# ==================================================================
def _reload_engine() -> None:
    """把进程内缓存的那个检索器/引擎丢掉，让它下次请求时重新从磁盘加载。

    为什么要这么一个函数（不写会出什么问题）：
        检索器是"启动时读一次、之后一直用内存里那份"的设计（为了快）。
        刚建好的库在**磁盘**上，而内存里那份还是旧的 ——
        不重置的话，出现了最让人困惑的一类现象：
        **后台显示"已入库"，但提问搜不到它**。
        用户会去质疑向量库、质疑检索参数，唯独想不到是内存缓存。

    为什么只置空、不主动重建：
        重建要几秒（读语料 + 建 BM25 索引 + 加载 FAISS）。
        放在这里同步做的话，用户点完"重新入库"后浏览器会多等几秒；
        而且紧接着的那次请求本来就要加载它。
        置空 = "下次用到时再加载"，把代价挪到真正需要它的那一刻。

    ⚠️ 为什么要 import 两个模块内部的私有全局变量：
        这两个单例分散在两个模块里（_engine / _retriever），
        各自只提供了 getter。与其在别处硬改它们的私有变量
        （那样耦合更难查），不如在**各自的模块里**提供一个正规的重置函数
        （rag_service.reset_engine / hybrid.reset_retriever），
        这里只是按顺序调用它们。顺序无所谓 —— 两个都会被重新创建。
    """
    from backend.app.retrieval.hybrid import reset_retriever
    from backend.app.services.rag_service import reset_engine

    reset_engine()
    reset_retriever()
    _log("检索器已重置，新内容下次提问即可命中")


# ==================================================================
# 七、失败处理
# ==================================================================
def _mark_failed(doc_id: int, message: str) -> None:
    """把一份手册标成 failed，并记下原因。

    ⚠️ 这个函数自己也要兜异常，理由有点绕但很实际：
        它是在 `_run_safely` 的 except 分支里被调用的。
        如果它自己再抛异常（比如数据库正好锁住了），
        那个异常会从 `_run_safely` 里冒出去 —— 而 `_run_safely` 已经是
        最后一道防线了，它一冒出去，**状态就永远停在 indexing**。
        所以这里再包一层，失败就只打日志。
    """
    db = SessionLocal()
    try:
        doc = document_service.get(db, doc_id)
        document_service.set_state(
            db, doc,
            status=STATUS_FAILED,
            stage="建库失败",
            error=message[-4000:],       # 截一下，避免超长报错撑爆字段
        )
    except Exception as e:      # noqa: BLE001 —— 见上面说明
        _log(f"写失败状态时又出错了（doc_id={doc_id}）：{e}")
    finally:
        db.close()


__all__ = ["get_progress", "is_running", "remove_source", "shutdown_executor", "submit"]
