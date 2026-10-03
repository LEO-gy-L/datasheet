# -*- coding: utf-8 -*-
"""
评测脚本：跑一遍 eval/qa_pairs.json，算出 RAG 的两个核心指标
==============================================================
为什么要有它：
    简历上写"实现了 RAG 问答"，面试官一定会问"你怎么证明它答得准？"
    这个脚本给出两个可量化的指标：
      1. 答案包含率 —— 模型回答里有没有出现标准答案的关键词
      2. 检索命中率 —— 标准答案所在页有没有被检索到（这才是 RAG 的真正瓶颈）

字段约定（见 eval/qa_pairs.json）：
    expected_answer_contains : 关键词列表，【任意一个】出现即算命中（ANY 语义）
    expected_source_pages    : 期望答案来自哪些页

运行方法（在 datasheet 项目根目录下）：
    .venv\\Scripts\\python backend\\eval.py
    .venv\\Scripts\\python backend\\eval.py --k 6
    .venv\\Scripts\\python backend\\eval.py --source STM32F103C8_Datasheet.pdf

注意：这一步会真正调用 embedding + DeepSeek 接口，会产生少量费用（几分钱）。
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

# 让这个脚本无论从哪个目录运行，都能 import 到同目录下的 rag_engine
sys.path.insert(0, str(Path(__file__).resolve().parent))

from rag_engine import RAGEngine   # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QA = ROOT / "eval" / "qa_pairs.json"


def load_pairs(path: Path) -> list[dict]:
    """读评测集 JSON 文件。"""
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize(text: str) -> str:
    """去掉商标符号，避免 Cortex®-M3 匹配不上 Cortex-M3。"""
    return text.lower().replace("\u00ae", "").replace("\u2122", "")


def check_keywords(answer: str, keywords: list[str]) -> tuple[bool, str | None]:
    """
    关键词检查：任意一个出现就算命中（ANY 语义）。

    为什么是 ANY 而不是 ALL：
        同一个事实有 "128 Kbytes" / "128 KB" 等多种写法，
        要求全部出现会把正确答案误判成失败。比对时不区分大小写。
    """
    if not keywords:
        return True, None
    low = _normalize(answer)
    for kw in keywords:
        if _normalize(kw) in low:
            return True, kw
    return False, None


def pages_in_chunks(chunks, expected_pages: list[int]) -> list[int]:
    """
    看期望页码有没有出现在召回块的 page_start ~ page_end 区间里。

    为什么要处理成区间：跨页续表那一块的 metadata 是 page_start=28, page_end=33，
    只比对 page_start 会漏掉。
    """
    got: set[int] = set()
    for c in chunks:
        ps = c.metadata.get("page_start")
        pe = c.metadata.get("page_end")
        if not ps:
            continue
        try:
            for p in range(int(ps), int(pe or ps) + 1):
                got.add(p)
        except ValueError:
            continue
    return [p for p in expected_pages if p in got]


def main() -> None:
    ap = argparse.ArgumentParser(description="评测 RAG 问答效果")
    ap.add_argument("--qa", default=str(DEFAULT_QA), help="问答对 JSON 路径")
    ap.add_argument("--k", type=int, default=4, help="检索 top-k（默认 4）")
    ap.add_argument("--source", default=None, help="只查某份手册（source 文件名）")
    args = ap.parse_args()

    qa_path = Path(args.qa)
    if not qa_path.exists():
        raise SystemExit(f"找不到评测集：{qa_path}")

    pairs = load_pairs(qa_path)
    engine = RAGEngine(k=args.k)

    print("=" * 70)
    print(f"评测开始：共 {len(pairs)} 条问答对，top-k = {args.k}")
    if args.source:
        print(f"限定手册：{args.source}")
    print("=" * 70)

    rows: list[dict] = []

    for item in pairs:
        q = item["question"]
        source = item.get("source") or args.source
        try:
            res = engine.ask(q, source=source)
        except Exception as e:
            print(f"\n[失败] {q}")
            print(f"       原因：{e}")
            rows.append({"answer_hit": False, "page_hit": False, "seconds": 0.0})
            continue

        answer = res["answer"]
        chunks = res["chunks"]

        kw_hit, matched = check_keywords(answer, item.get("expected_answer_contains", []))
        hit_pages = pages_in_chunks(chunks, item.get("expected_source_pages", []))

        rows.append({
            "answer_hit": kw_hit,
            "page_hit": bool(hit_pages),
            "seconds": res["seconds"],
        })

        print(f"\n[{'OK  ' if kw_hit else 'MISS'}] {q}")
        print(f"       回答：{answer[:120]}...")
        print(f"       关键词命中：{matched or '无'}")
        print(f"       期望页码 {item.get('expected_source_pages', [])}"
              f" -> 实际召回页码命中 {hit_pages}")
        print(f"       耗时：{res['seconds']} 秒")

    total = len(rows)
    ans_rate = sum(1 for r in rows if r["answer_hit"]) / total if total else 0
    pg_rate = sum(1 for r in rows if r["page_hit"]) / total if total else 0
    times = [r["seconds"] for r in rows]

    print("\n" + "=" * 70)
    print("评测汇总")
    print("=" * 70)
    print(f"  答案包含率 : {ans_rate:.0%}   "
          f"({sum(1 for r in rows if r['answer_hit'])}/{total})")
    print(f"  检索命中率 : {pg_rate:.0%}   "
          f"({sum(1 for r in rows if r['page_hit'])}/{total})")
    if times:
        print(f"  平均耗时   : {statistics.mean(times):.2f} 秒")
    print()
    print("  提示：检索命中率低 -> 调大 --k 或改切块参数；")
    print("        检索命中但答案不含关键词 -> 改 backend/rag_engine.py 里的 PROMPT_TEMPLATE。")


if __name__ == "__main__":
    main()
