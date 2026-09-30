# -*- coding: utf-8 -*-
"""
第 4 步：完整的 RAG 问答（命令行版）
======================================
流程：用户提问 → 向量库检索 → 拼 prompt → 发给 DeepSeek → 打印答案和出处

RAG 的全部逻辑已经搬到 src/rag_engine.py，这里只负责"读输入 + 打印"。

运行方法：
    .venv\\Scripts\\python src\\step4_rag.py
然后直接输入问题，比如：GPIO 最大输出电流是多少？
输入 quit 退出。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rag_engine import RAGEngine   # noqa: E402


def print_answer(result: dict, question: str) -> None:
    """把一次问答的结果打印出来。"""
    print("\n" + "=" * 60)
    print("问题：", question)
    print("-" * 60)
    print("回答：", result["answer"])
    print("-" * 60)
    print("答案来源：", "、".join(result["sources"]))
    print("耗时：", result["seconds"], "秒")
    print("=" * 60)


# ---------- 命令行交互循环 ----------
if __name__ == "__main__":
    try:
        engine = RAGEngine()
    except SystemExit as e:
        raise e

    print("Datasheet 问答系统已启动，输入问题开始提问，输入 quit 退出")
    while True:
        question = input("\n请输入问题：").strip()
        if question.lower() == "quit":
            print("再见！")
            break
        if not question:
            continue
        try:
            result = engine.ask(question)
        except Exception as e:
            print(f"[出错] {e}")
            continue
        print_answer(result, question)
