# -*- coding: utf-8 -*-
"""
入口函数，负责读输入和打印
======================================
流程：用户提问 → 向量库检索 → 拼 prompt → 发给 DeepSeek → 打印答案和出处
运行方法：
    python -m backend.scripts.chat
然后直接输入问题，比如：GPIO 最大输出电流是多少？
输入 quit 退出。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 项目根
# 把项目根加入 sys.path，这样才能 import 到 backend 包

from backend.app.services.rag_service import RAGEngine   # noqa: E402


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
    except IndexNotFoundError as e:
        print(f"\n[启动失败] {e}\n")
        raise SystemExit(1) from None

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
