# -*- coding: utf-8 -*-
"""
第 4 步：完整的 RAG 问答（项目核心）
======================================
流程：用户提问 → 向量库检索最相关的几块原文 → 把原文+问题拼成 prompt
      → 发给 DeepSeek → 模型"看着原文"回答 → 打印答案和出处

运行方法：
    .venv\\Scripts\\python src\\step4_rag.py
然后直接输入问题，比如：GPIO 最大输出电流是多少？
输入 quit 退出。
"""

from pathlib import Path
from dotenv import load_dotenv
from langchain_community.embeddings import ZhipuAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_deepseek import ChatDeepSeek

# ---------- 0. 准备工作 ----------
load_dotenv()
BASE_DIR = Path(__file__).resolve().parents[1]
STORE_DIR = BASE_DIR / "vectorstore"

if not (STORE_DIR / "index.faiss").exists():
    raise SystemExit("没找到向量库，请先运行：.venv\\Scripts\\python src\\step3_vectorstore.py")

# 加载第 3 步保存的向量库
# allow_dangerous_deserialization 是因为索引文件里存了 Python 对象，
# 自己建的库自己加载是安全的，官方要求显式声明
embeddings = ZhipuAIEmbeddings(model="embedding-3")
vectorstore = FAISS.load_local(
    str(STORE_DIR),
    embeddings,
    allow_dangerous_deserialization=True,
)

model = ChatDeepSeek(model="deepseek-chat", temperature=0)

# ---------- 1. 定义问答函数 ----------
def ask(question: str) -> None:
    """一次完整的 RAG 问答：检索 → 拼 prompt → 调模型 → 打印"""

    # (1) 检索：把问题也变成向量，找出意思最接近的 4 块原文
    #     similarity_search 返回一个 Document 列表
    related_chunks = vectorstore.similarity_search(question, k=4)

    # (2) 把这几块原文拼成一大段 context（上下文）
    context = "\n\n".join(chunk.page_content for chunk in related_chunks)

    # (3) 拼 prompt：这是 RAG 的灵魂——"只能根据下面的资料回答"
    prompt = f"""你是一个芯片数据手册问答助手。请只根据下面提供的资料回答问题。
如果资料里没有答案，就直接说"数据手册中没有提到"，不要自己编。

【资料】
{context}

【问题】
{question}

【回答】"""

    # (4) 调模型
    response = model.invoke(prompt)

    # (5) 打印答案
    print("\n" + "=" * 60)
    print("回答：", response.content)
    print("-" * 60)

    # (6) 打印出处：让用户能核对答案是从哪份文件、第几页来的（面试亮点：可追溯）
    #     用 list 而不是 set：set 的迭代顺序每次都不一样，来源顺序会跳
    sources: list[str] = []
    for chunk in related_chunks:
        name = Path(chunk.metadata.get("source", "未知")).name
        ps = chunk.metadata.get("page_start")
        pe = chunk.metadata.get("page_end")
        if ps and pe and pe != ps:
            label = f"{name} 第 {ps}-{pe} 页"
        elif ps:
            label = f"{name} 第 {ps} 页"
        else:
            label = name
        if label not in sources:
            sources.append(label)
    print("答案来源：", "、".join(sources))
    print("token 用量：", response.usage_metadata)
    print("=" * 60)

# ---------- 2. 命令行交互循环 ----------
if __name__ == "__main__":
    print("Datasheet 问答系统已启动，输入问题开始提问，输入 quit 退出")
    while True:
        question = input("\n请输入问题：").strip()
        if question.lower() == "quit":
            print("再见！")
            break
        if not question:
            continue
        ask(question)
