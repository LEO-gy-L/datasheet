# -*- coding: utf-8 -*-
"""
P1 第 2 步：把 chunks.jsonl 灌进 FAISS 向量库（新补上的"断链"环节）
====================================================================

【为什么必须要有这个脚本 —— 这是整个项目最要命的一个缺口】

  完整的数据流本来应该是：
      PDF → P0 清洗(表格/正文) → P1 切块(chunks.jsonl) → 向量化入库 → 检索问答
                                        ↑
                              原来这里断了：没有任何脚本读 chunks.jsonl

  之前的 step3_vectorstore.py 直接用 PyPDFLoader 读**原始 PDF**，
  完全不经过 P0/P1 的清洗成果。结果就是：
    - 你辛苦清洗出的表格/正文，问答链路一个字都用不到
    - vectorstore/ 里其实只有一个 4 个向量的旧库（内容还是 WB32F 示例 txt）
    - 问 "GPIO 最大电流"，模型拿示例文本一本正经地回答你

  本脚本补上这一环：读 data/chunks_v2/**/chunks.jsonl → 调 embedding → 存 FAISS。

运行方法（在项目根目录 datasheet 下）：
    # 先空跑，只统计不花钱（不调 embedding 接口）
    .venv\\Scripts\\python src\\p1_2_index.py --dry-run

    # 真正建库（会调智谱 embedding 接口，把每块文字换成向量）
    .venv\\Scripts\\python src\\p1_2_index.py

    # 只建某一份手册的库
    .venv\\Scripts\\python src\\p1_2_index.py --stem STM32F103C8_Datasheet

输出：
    vectorstore/index.faiss      向量索引
    vectorstore/index.pkl        原文 + 元数据
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
ROOT = Path(__file__).resolve().parents[1]

CHUNKS_ROOT = ROOT / "data" / "chunks_v2"
STORE_DIR = ROOT / "vectorstore"

EMBED_MODEL = "embedding-3"     # 智谱的 embedding-3
BATCH_SIZE = 16                 # 每批送多少个块去向量化（攒批调用，减少请求次数）


def load_chunks(chunks_root: Path, only_stem: str | None) -> tuple[list[Document], dict]:
    """
    读 chunks.jsonl，转成 LangChain 的 Document 列表。

    每块 JSON 的字段（chunk_loader.py 写出来的）：
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
    stats = {"text": 0, "table": 0, "empty": 0, "files": []}

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

                docs.append(Document(
                    page_content=content,
                    metadata={
                        "id": c.get("id", ""),
                        "source": c.get("source", stem),      # 手册文件名
                        "type": c.get("type", ""),            # text / table
                        "title": c.get("title", ""),          # 章节路径 或 表格标题
                        "page_start": c.get("page_start", 0),
                        "page_end": c.get("page_end", 0),
                        "part": c.get("part", ""),
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
    """
    vectors: list[tuple[str, list[float]]] = []
    n_batches = -(-len(docs) // BATCH_SIZE)

    for i in range(0, len(docs), BATCH_SIZE):
        batch = docs[i:i + BATCH_SIZE]
        texts = [d.page_content for d in batch]
        batch_no = i // BATCH_SIZE + 1
        print(f"  向量化 第 {batch_no}/{n_batches} 批（{len(batch)} 块）……", flush=True)
        emb = embeddings.embed_documents(texts)
        vectors.extend(zip(texts, emb))

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
        print("       请先运行：.venv\\Scripts\\python src\\chunk_loader.py")
        return

    print("① 读取切块结果")
    docs, stats = load_chunks(CHUNKS_ROOT, args.stem)

    if not docs:
        print("\n[错误] 一块都没读到。请确认 chunk_loader.py 已经跑过，"
              "且 data/chunks_v2/<手册名>/chunks.jsonl 不为空。")
        return

    if args.limit:
        docs = docs[:args.limit]
        print(f"  （--limit 生效，只取前 {len(docs)} 块）")

    total_chars = sum(len(d.page_content) for d in docs)
    print()
    print(f"  合计 {len(docs)} 块  ·  {total_chars:,} 字符"
          f"  ·  约 {int(total_chars / 3.5):,} token")
    print(f"  其中 正文 {stats.get('text', 0)} 块，表格 {stats.get('table', 0)} 块")
    if stats.get("empty"):
        print(f"  （另有 {stats['empty']} 条空内容已跳过）")

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

    # ---------- 检查密钥 ----------
    key = os.getenv("ZHIPUAI_API_KEY")
    if not key or "在这里填" in key:
        print()
        print("[错误] .env 里没有有效的 ZHIPUAI_API_KEY，无法向量化。")
        print("       请先在项目根目录的 .env 里填入智谱的 API Key。")
        return

    # ---------- 建库 ----------
    print()
    print("② 向量化（这一步会调用智谱接口，几百块大概要几分钟）")
    embeddings = ZhipuAIEmbeddings(model=EMBED_MODEL)
    t0 = time.time()
    store = build_index(docs, embeddings)
    print(f"  向量化完成，用时 {time.time() - t0:.1f} 秒")

    # ---------- 落盘 ----------
    print()
    print("③ 保存到本地")
    STORE_DIR.mkdir(parents=True, exist_ok=True)

    # 先把旧的索引文件删掉：不然万一新库保存失败，
    # 旧的 index.faiss 还在，step4 会加载到一个"上一版的库"而没有报错
    for name in ("index.faiss", "index.pkl"):
        old = STORE_DIR / name
        if old.exists():
            old.unlink()
            print(f"  已删除旧文件 {name}")

    store.save_local(str(STORE_DIR))

    manifest = {
        "built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "embedding_model": f"zhipuai/{EMBED_MODEL}",
        "n_docs": len(docs),
        "n_text": stats.get("text", 0),
        "n_table": stats.get("table", 0),
        "total_chars": total_chars,
        "sources": by_source,
        "chunks_root": str(CHUNKS_ROOT.relative_to(ROOT)),
        "built_by": "src/p1_2_index.py",
    }
    (STORE_DIR / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("=" * 66)
    print("建库完成")
    print("=" * 66)
    print(f"  向量总数 : {store.index.ntotal}")
    print(f"  向量维度 : {store.index.d}")
    print(f"  索引文件 : {STORE_DIR.relative_to(ROOT)}/index.faiss")
    print(f"  建库清单 : {STORE_DIR.relative_to(ROOT)}/_manifest.json")
    print()
    print("  下一步可以问问题了：")
    print("    .venv\\Scripts\\python src\\step4_rag.py")


if __name__ == "__main__":
    main()
