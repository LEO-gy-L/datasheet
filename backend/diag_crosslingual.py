# -*- coding: utf-8 -*-
"""
诊断：中文提问 vs 英文提问，对同一份英文手册的召回结果对比
==========================================================
为什么需要它：
    我们的手册是英文的（STM32/ATmega datasheet），但用户用中文提问。
    如果"中文问题"和"英文原文"在向量空间里距离很远，检索就会召错页。
    这个脚本把同一个意思分别用中文/英文问一遍，对比召回的页码，
    用来判断命中率低到底是"切块问题"还是"跨语言语义鸿沟"。

运行方法（在项目根目录）：
    .venv\Scripts\python backend\diag_crosslingual.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv  # noqa: E402
from langchain_community.embeddings import ZhipuAIEmbeddings  # noqa: E402
from langchain_community.vectorstores import FAISS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

STORE_DIR = ROOT / "vectorstore"
EMBED_MODEL = "embedding-3"
SOURCE = "STM32F103C8_Datasheet.pdf"

# 每组是同一个意思的中文版 / 英文版
PAIRS = [
    ("Flash 存储器容量是多少？", "What is the Flash memory size?"),
    ("SRAM 有多大？", "How much SRAM is available?"),
    ("供电电压范围是多少？", "What is the supply voltage range?"),
    ("STM32F103 用的是什么内核？", "What CPU core does STM32F103 use?"),
    ("GPIO 最大输出电流是多少？", "What is the maximum GPIO output current?"),
]

TOP_K = 5


def main() -> None:
    embeddings = ZhipuAIEmbeddings(model=EMBED_MODEL)
    vs = FAISS.load_local(str(STORE_DIR), embeddings, allow_dangerous_deserialization=True)

    print("=" * 70)
    print(f"跨语言检索诊断：中文提问 vs 英文提问（限定手册 {SOURCE}）")
    print("=" * 70)

    for zh, en in PAIRS:
        print(f"\n问题含义：{zh}")
        print("-" * 70)

        for label, q in (("中文", zh), ("英文", en)):
            docs = vs.similarity_search(q, k=TOP_K, filter={"source": SOURCE})
            pages = [d.metadata.get("page_start") for d in docs]
            print(f"  [{label}] {q}")
            print(f"        召回页码 top{TOP_K}: {pages}")

    print("\n" + "=" * 70)
    print("怎么看结果：")
    print("  如果英文提问召回的页码明显更准（比如命中第 1 页概览），")
    print("  而中文提问召回偏到别的章节 —— 说明瓶颈是【跨语言语义鸿沟】，")
    print("  不是切块问题。修复方向是 query translation（把中文问题译成英文再检索）。")
    print("=" * 70)


if __name__ == "__main__":
    main()
