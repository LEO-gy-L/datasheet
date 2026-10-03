# -*- coding: utf-8 -*-
"""
P1 第 2 步：把 chunks.jsonl 灌进 FAISS 向量库（新补上的"断链"环节）
====================================================================

【为什么必须要有这个脚本 —— 这是整个项目最要命的一个缺口】

  完整的数据流本来应该是：
      PDF → P0 清洗(表格/正文) → P1 切块(chunks.jsonl) → 向量化入库 → 检索问答
                                        ↑
                              原来这里断了：没有任何脚本读 chunks.jsonl

  之前的 legacy/step3_vectorstore.py 直接用 PyPDFLoader 读**原始 PDF**，
  完全不经过 P0/P1 的清洗成果。结果就是：
    - 你辛苦清洗出的表格/正文，问答链路一个字都用不到
    - vectorstore/ 里其实只有一个 4 个向量的旧库（内容还是 WB32F 示例 txt）
    - 问 "GPIO 最大电流"，模型拿示例文本一本正经地回答你

  本脚本补上这一环：读 data/chunks_v2/**/chunks.jsonl → 调 embedding → 存 FAISS。

运行方法（在项目根目录 datasheet 下）：
    # 先空跑，只统计不花钱（不调 embedding 接口）
    python -m backend.app.ingestion.indexer --dry-run

    # 只落 BM25 语料 + 父块表，不建向量库、不花钱。
    # 混合检索里的"关键词路"只用 docs.jsonl，所以靠这一步就能完整体验
    # BM25 + RRF 融合（语义路会自动跳过，因为还没建）。
    python -m backend.app.ingestion.indexer --bm25-only

    # 真正建库（会调智谱 embedding 接口，把每块文字换成向量）
    python -m backend.app.ingestion.indexer

    # 只建某一份手册的库
    python -m backend.app.ingestion.indexer --stem STM32F103C8_Datasheet

输出：
    vectorstore/index.faiss      向量索引（--bm25-only 时不产出）
    vectorstore/index.pkl        原文 + 元数据（--bm25-only 时不产出）
    vectorstore/docs.jsonl       BM25 语料（扁平 JSONL，一行一块）
    vectorstore/parents.json     父块表（供检索命中后放大上下文）
    vectorstore/_manifest.json   建库清单（一眼看出库里是哪份手册、多少块）
"""

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from langchain_community.embeddings import ZhipuAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document


# ---------- 项目根目录 ----------
from backend.app.config import ROOT

CHUNKS_ROOT = ROOT / "data" / "chunks_v2"
STORE_DIR = ROOT / "vectorstore"

EMBED_MODEL = "embedding-3"     # 智谱的 embedding-3
BATCH_SIZE = 8                  # 每批送多少个块去向量化（攒批调用，减少请求次数）

# 2026-10-03 实测新增：重试与节流参数。
#
#   实测现象：连续跑 6 批（每批 16 块）时，第 6 批会被接口限流而失败，
#   但把同一批单独拿出来重跑又能成功 —— 典型的速率限制（rate limit），
#   不是内容有问题。旧版代码没做重试，一次限流就让整轮建库白跑
#   （前 5 批的 token 已经花掉了，向量却全丢）。
#
#   修法就是两件事，都是接口调用里的标准套路：
#     ① 批与批之间歇一下（BATCH_INTERVAL），别把请求打得太密
#     ② 失败不立刻投降，等一会儿再试，而且**越试等得越久**（指数退避）
EMBED_RETRIES = 4               # 一批最多试 4 次
EMBED_RETRY_WAIT = 5.0          # 首次重试等 5 秒，之后 10、20 秒（2 的幂次增长）
BATCH_INTERVAL = 1.5            # 每批之间固定歇 1.5 秒

# 为什么等待时间从 2 秒改成 5 秒、批大小从 16 改成 8：
#   中途排查出两类不同的失败，都遇到过，所以两道防线都要留：
#     ① 参数错误（HTTP 400 / code 1210）—— 某一块的索引文本超过接口
#        单条 3072 token 上限。这是**确定性**错误，重试一万次也没用，
#        靠的是下面的 clip_index_text 兜底和 chunking 的分片修正。
#     ② 偶发限流 —— 连续请求太密被拒，等一会儿重发同一批就能过。
#   所以：批做小一点、间隔拉长一点（摊平速率），
#   同时保留重试（治偶发），靠日志里的错误原文区分到底是哪一种。

# 索引文本的**硬**上限（兜底，防炸）。注意它和 chunking 里的
# TABLE_INDEX_MAX_CHARS（1500）**不是一回事**，两个值故意不一样：
#
#   chunking.TABLE_INDEX_MAX_CHARS = 1500  ->  **软目标**
#       分片时的努力方向。因为是按行平摊估算的（拿不到每行精确的数据点数），
#       实际产出会飘一点 —— 实测最长的片落在 1825 字符，比目标高 20%。
#
#   indexer.INDEX_TEXT_MAX_CHARS = 2200    ->  **硬兜底**
#       只在真的危险时才动手。embedding-3 单条硬上限是 3072 token，
#       2200 字符仍在其下；而 1500 那个软目标产出的 1825 落在两者之间，
#       不会被截 —— 这才对：分片已经尽力了，不该再被砍一刀尾巴，
#       否则等于白分（数据点在索引里丢了，检索不到）。
#
#   如果两个值都设 1500，就会出这个矛盾：chunking 辛苦切出的 1825 字符片，
#   到 indexer 又被截回 1500 —— 最后那几条数据点白丢，而且没有任何报错。
INDEX_TEXT_MAX_CHARS = 2200


def clip_index_text(text: str, max_chars: int = INDEX_TEXT_MAX_CHARS) -> str:
    r"""把过长的索引文本截到 max_chars 以内，**尽量在行边界切**。

    为什么按行切而不是直接 text[:max_chars]：
        索引文本的每一行都是一条完整的自描述句
        （"CH32F103 C6T6 · 芯片引脚数 = 48"）。
        从中间硬切会把最后一条切成半句 ——
        变成 "CH32F103 C6T6 · 芯片引脚" 这种**错误信息**，
        比直接不要它更糟：它看起来像个真的数据点，会误导检索和模型。

    只有"第一行本身就超长"时才退化成硬切（那时别无选择）。
    """
    if len(text) <= max_chars:
        return text

    kept: list[str] = []
    used = 0
    for line in text.splitlines():
        # +1 是换行符本身占的位置
        if used + len(line) + 1 > max_chars:
            break
        kept.append(line)
        used += len(line) + 1

    if not kept:
        # 第一行就超长 -> 只能硬切
        return text[:max_chars]
    return "\n".join(kept)


def load_chunks(chunks_root: Path, only_stem: str | None) -> tuple[list[Document], dict]:
    """
    读 chunks.jsonl，转成 LangChain 的 Document 列表。

    每块 JSON 的字段（app/ingestion/chunking.py 写出来的）：
        id / type / source / title / page_start / page_end / part / n_chars / content

    为什么要转成 Document：
        LangChain 的向量库只认 Document 对象（page_content = 要被向量化的文字，
        metadata = 附带的出处信息）。metadata 会在检索命中后跟着返回，
        这样前端才能显示"这条答案来自第几页"。
    """
    if only_stem:
        stems = [only_stem]
    else:
        stems = sorted(d.name for d in chunks_root.iterdir() if d.is_dir())

    docs: list[Document] = []
    # clipped：有多少块的索引文本被兜底截断了（见 clip_index_text）。
    # 单独统计出来、并在报告里打印 —— 本项目的硬规矩是"不静默丢东西"，
    # 截断属于丢内容，必须让人看得见。
    stats = {"text": 0, "table": 0, "empty": 0, "clipped": 0, "files": []}

    for stem in stems:
        jsonl = chunks_root / stem / "chunks.jsonl"
        if not jsonl.exists():
            print(f"  [跳过] 找不到 {jsonl.relative_to(ROOT)}")
            continue

        n_before = len(docs)
        with jsonl.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                c = json.loads(line)
                content = (c.get("content") or "").strip()
                if not content:
                    stats["empty"] += 1
                    continue

                # ── 索引文本 vs 展示文本（2026-10-03 新增）────────────────
                #
                #   index_text -> **拿去向量化的文字**
                #       表格块 = 自描述句
                #                "CH32F103 C6T6 · 芯片引脚数 = 48"
                #                每个数值都绑着自己的型号表头和指标名，检索才准
                #       正文块 = 正文本身
                #
                #   content -> **原文**（markdown 表格 / 带标题的正文）
                #       检索命中之后，展示给用户、送给 LLM 用的是这一份
                #
                # 为什么必须分开：
                #   markdown 表格长这样 ——  | 芯片引脚数 | 48 | 48 | 48 | 64 |
                #   把这一行拿去做向量化，只能得到"这张表里有个 48"这种没用的
                #   语义，BM25 也只能匹配到孤立的 "48" 这个 token。
                #   换成自描述句之后，"CH32F103 C6T6" 和 "芯片引脚数"
                #   才是完整可匹配的串。
                index_text = (c.get("index_text") or "").strip() or content

                # 最后一道兜底：切块阶段已经按 TABLE_INDEX_MAX_CHARS 分过片，
                # 正常不会超；万一还有漏网的（单行超长等），这里截掉尾巴，
                # 避免它一条就把整轮建库搞成 400。截了多少会被统计并打印出来。
                clipped = clip_index_text(index_text)
                if len(clipped) < len(index_text):
                    stats["clipped"] += 1
                index_text = clipped

                docs.append(Document(
                    page_content=index_text,
                    metadata={
                        "id": c.get("id", ""),
                        "content": content,                   # 原文，命中后展示用
                        "source": c.get("source", stem),      # 手册文件名
                        "type": c.get("type", ""),            # text / table / figure
                        "title": c.get("title", ""),          # 章节路径 或 表格标题
                        "page_start": c.get("page_start", 0),
                        "page_end": c.get("page_end", 0),
                        "part": c.get("part", ""),
                        "parent_id": c.get("parent_id", ""),  # 父块 id，供放大上下文
                    },
                ))
                stats[c.get("type", "text")] = stats.get(c.get("type", "text"), 0) + 1

        stats["files"].append((stem, len(docs) - n_before))
        print(f"  已读入 {jsonl.relative_to(ROOT)}  （{len(docs) - n_before} 块）")

    return docs, stats


def build_index(docs: list[Document], embeddings) -> FAISS:
    """
    分批把文档向量化，再建 FAISS 索引。

    为什么要分批（而不是一句 FAISS.from_documents 搞定）：
      1. from_documents 内部也是一块块调接口，但它不告诉你进度 ——
         几百块跑几分钟，你会以为死机了
      2. 分批可以自己打印"第 3/12 批"，出错了也知道断在哪一批
      3. 攒批（每批 16 块）比一块一次请求更快，也更不容易被限流

    为什么要重试（见文件头 EMBED_RETRIES 那段实测记录）：
        接口有速率限制，连续请求太密会被拒。被拒不是"这块内容有问题"，
        等一两秒再发同样的请求就好了。加一层指数退避重试，
        把"偶发限流"和"真失败"区分开 —— 偶发的自动恢复，真的就报错。
    """
    vectors: list[tuple[str, list[float]]] = []
    n_batches = -(-len(docs) // BATCH_SIZE)

    for i in range(0, len(docs), BATCH_SIZE):
        batch = docs[i:i + BATCH_SIZE]
        texts = [d.page_content for d in batch]
        batch_no = i // BATCH_SIZE + 1
        print(f"  向量化 第 {batch_no}/{n_batches} 批（{len(batch)} 块）……", flush=True)

        # ---- 带指数退避的重试 ----
        emb: list[list[float]] | None = None
        for attempt in range(EMBED_RETRIES):
            try:
                emb = embeddings.embed_documents(texts)
                break
            except Exception as e:
                last = attempt == EMBED_RETRIES - 1
                if last:
                    # 试到最后一次还是不行 —— 这时候才真的往外抛。
                    # 抛出去而不是吞掉：建到一半的库是**最坏的结果**，
                    # 它会安静地少一批向量，检索时表现为"某些内容怎么都搜不到"，
                    # 极难排查。宁可让脚本整体失败，也不要留下一个残缺的库。
                    raise
                # 2 → 4 → 8 秒。为什么指数增长而不是固定 2 秒：
                # 如果是被限流，固定间隔重试往往还是会被打到同一堵墙上；
                # 越等越久能让对方的限流窗口真正滑过去。
                wait = EMBED_RETRY_WAIT * (2 ** attempt)
                # 把**错误原文**打出来 —— 限流、超额、鉴权失败长得完全不一样，
                # 不看原文就只能瞎猜（实测过：先猜"内容太长"、再猜"发太快"，
                # 都对不上，最后是错误消息才指明了方向）。
                print(f"    第 {batch_no} 批失败（{type(e).__name__}: {str(e)[:220]}），"
                      f"{wait:.0f}s 后重试（第 {attempt + 2}/{EMBED_RETRIES} 次）", flush=True)
                time.sleep(wait)

        assert emb is not None          # 上面要么赋值要么抛异常，这里不可能为 None
        vectors.extend(zip(texts, emb))

        if batch_no < n_batches:
            time.sleep(BATCH_INTERVAL)  # 批间喘口气，降低被限流的概率

    metadatas = [d.metadata for d in docs]
    return FAISS.from_embeddings(
        text_embeddings=vectors,
        embedding=embeddings,
        metadatas=metadatas,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="把 chunks.jsonl 灌进 FAISS 向量库")
    ap.add_argument("--stem", default=None,
                    help="只索引某一份手册（data/chunks_v2/<stem>）；不传则索引全部")
    ap.add_argument("--dry-run", action="store_true",
                    help="只统计不建库（不调用 embedding 接口，不花钱）")
    ap.add_argument("--bm25-only", action="store_true",
                    help="跳过向量化和 FAISS，只落 BM25 语料 docs.jsonl / 父块表 parents.json"
                         "（同样不花钱，可以先用它验证混合检索里的关键词路）")
    ap.add_argument("--limit", type=int, default=0,
                    help="只取前 N 块（用来先跑通链路，0 = 不限制）")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")

    print("=" * 66)
    print("建向量库：chunks.jsonl → FAISS")
    print("=" * 66)
    print(f"  数据源    : {CHUNKS_ROOT.relative_to(ROOT)}")
    print(f"  输出      : {STORE_DIR.relative_to(ROOT)}")
    print(f"  embedding : 智谱 {EMBED_MODEL}")
    print()

    if not CHUNKS_ROOT.exists():
        print(f"[错误] 找不到 {CHUNKS_ROOT.relative_to(ROOT)}")
        print("       请先运行：python -m backend.app.ingestion.chunking")
        return

    print("① 读取切块结果")
    docs, stats = load_chunks(CHUNKS_ROOT, args.stem)

    if not docs:
        print("\n[错误] 一块都没读到。请确认 app/ingestion/chunking.py 已经跑过，"
              "且 data/chunks_v2/<手册名>/chunks.jsonl 不为空。")
        return

    if args.limit:
        docs = docs[:args.limit]
        print(f"  （--limit 生效，只取前 {len(docs)} 块）")

    total_chars = sum(len(d.page_content) for d in docs)
    print()
    print(f"  合计 {len(docs)} 块  ·  {total_chars:,} 字符"
          f"  ·  约 {int(total_chars / 3.5):,} token")
    print(f"  其中 正文 {stats.get('text', 0)} 块，"
          f"表格 {stats.get('table', 0)} 块，"
          f"图形指针 {stats.get('figure', 0)} 块")
    if stats.get("empty"):
        print(f"  （另有 {stats['empty']} 条空内容已跳过）")
    if stats.get("clipped"):
        print(f"  ⚠️ 有 {stats['clipped']} 块的索引文本超过 {INDEX_TEXT_MAX_CHARS} 字符，"
              f"已按行截断 —— 正常不该发生，建议回查 ingestion/chunking.py 的分片逻辑")

    # 来源分布：一眼看出库里到底装的是不是你要的手册
    by_source: dict[str, int] = {}
    for d in docs:
        by_source[d.metadata["source"]] = by_source.get(d.metadata["source"], 0) + 1
    print("  来源分布：")
    for s, n in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"      {s}  ->  {n} 块")

    if args.dry_run:
        print()
        print("② --dry-run：到这里就停，不调 embedding 接口、不写任何文件。")
        print()
        print("   示例块（前 300 字符）：")
        print("   " + "-" * 60)
        print("   " + docs[0].page_content[:300].replace("\n", "\n   "))
        print("   " + "-" * 60)
        return

    # ---------- ② 向量化（--bm25-only 时整段跳过）----------
    store = None
    if args.bm25_only:
        print()
        print("② --bm25-only：跳过向量化和 FAISS，只落 BM25 语料 / 父块表 / 清单。")
        print("   不调用 embedding 接口、不花钱；之后随时可以再跑一次完整建库。")
    else:
        # ---------- 检查密钥 ----------
        key = os.getenv("ZHIPUAI_API_KEY")
        if not key or "在这里填" in key:
            print()
            print("[错误] .env 里没有有效的 ZHIPUAI_API_KEY，无法向量化。")
            print("       请先在项目根目录的 .env 里填入智谱的 API Key。")
            print("       想先不花钱验证检索链路，可以改用：")
            print("       python -m backend.app.ingestion.indexer --bm25-only")
            return

        # ---------- 建库 ----------
        print()
        print("② 向量化（这一步会调用智谱接口，几百块大概要几分钟）")
        embeddings = ZhipuAIEmbeddings(model=EMBED_MODEL)
        t0 = time.time()
        store = build_index(docs, embeddings)
        print(f"  向量化完成，用时 {time.time() - t0:.1f} 秒")

    # ---------- ③ 落盘 ----------
    print()
    print("③ 保存到本地")
    STORE_DIR.mkdir(parents=True, exist_ok=True)

    if store is not None:
        # 先把旧的索引文件删掉：不然万一新库保存失败，
        # 旧的 index.faiss 还在，检索时会加载到一个"上一版的库"而没有报错
        for name in ("index.faiss", "index.pkl"):
            old = STORE_DIR / name
            if old.exists():
                old.unlink()
                print(f"  已删除旧文件 {name}")
        store.save_local(str(STORE_DIR))
    else:
        print("  （--bm25-only：已有的 index.faiss 保持不动）")

    # ---------- 导出 docs.jsonl（供 BM25 使用）----------
    # BM25 是纯文本检索，不需要向量，但需要把全部索引文本一次读进内存来
    # 建倒排索引。直接从 FAISS 的 pkl 里反查很别扭，落一份扁平文件最省事。
    docs_path = STORE_DIR / "docs.jsonl"
    with docs_path.open("w", encoding="utf-8") as fp:
        for d in docs:
            m = d.metadata
            fp.write(json.dumps({
                "id": m["id"],
                "index_text": d.page_content,      # 建 BM25 用的文本
                "content": m["content"],           # 原文，命中后展示
                "source": m["source"],
                "type": m["type"],
                "title": m["title"],
                "page_start": m["page_start"],
                "page_end": m["page_end"],
                "parent_id": m.get("parent_id", ""),
            }, ensure_ascii=False) + "\n")

    # ---------- 合并 parents.jsonl -> parents.json（供"父块放大"用）----------
    # 切块阶段每份手册各写一个 parents.jsonl，这里合并成一个大字典，
    # 服务启动时一次性读进内存，检索命中后按 parent_id 直接 O(1) 取到。
    parents: dict[str, dict] = {}
    if CHUNKS_ROOT.exists():
        for stem_dir in sorted(p for p in CHUNKS_ROOT.iterdir() if p.is_dir()):
            pf = stem_dir / "parents.jsonl"
            if not pf.exists():
                continue
            for line in pf.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    item = json.loads(line)
                    parents[item["parent_id"]] = item
    parents_path = STORE_DIR / "parents.json"
    parents_path.write_text(
        json.dumps(parents, ensure_ascii=False), encoding="utf-8")

    manifest = {
        "built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "bm25-only" if args.bm25_only else "full",
        "embedding_model": None if args.bm25_only else f"zhipuai/{EMBED_MODEL}",
        "n_docs": len(docs),
        "n_text": stats.get("text", 0),
        "n_table": stats.get("table", 0),
        "n_figure": stats.get("figure", 0),
        "n_clipped": stats.get("clipped", 0),
        "n_parents": len(parents),
        "total_chars": total_chars,
        "sources": by_source,
        "chunks_root": str(CHUNKS_ROOT.relative_to(ROOT)),
        "built_by": "-m backend.app.ingestion.indexer"
                    + (" --bm25-only" if args.bm25_only else ""),
        "note": "page_content = index_text（自描述句/正文）；"
                "metadata.content = 原文，命中后展示用",
    }
    (STORE_DIR / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("=" * 66)
    print("建库完成" + ("（仅 BM25 语料）" if args.bm25_only else ""))
    print("=" * 66)
    if store is not None:
        print(f"  向量总数 : {store.index.ntotal}")
        print(f"  向量维度 : {store.index.d}")
        print(f"  索引文件 : {STORE_DIR.relative_to(ROOT)}/index.faiss")
    else:
        print(f"  向量     : （--bm25-only，未建；语义检索路会静默跳过）")
    print(f"  BM25 语料: {STORE_DIR.relative_to(ROOT)}/docs.jsonl（{len(docs)} 条）")
    print(f"  父块表   : {STORE_DIR.relative_to(ROOT)}/parents.json（{len(parents)} 个）")
    print(f"  建库清单 : {STORE_DIR.relative_to(ROOT)}/_manifest.json")
    print()
    print("  下一步可以试混合检索了：")
    print("    python -m backend.app.retrieval.hybrid \"CH32F103C6T6 的引脚数是多少\"")
    print("  想启动服务问问题：")
    print("    python -m backend.scripts.chat")


if __name__ == "__main__":
    main()
