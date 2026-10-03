# -*- coding: utf-8 -*-
"""
RAG 引擎（把重复三遍的逻辑合并到这里）
=======================================
为什么要有这个文件：
    原来 main.py / api.py / app.py 里各有一份几乎一样的：
        similarity_search -> 拼 prompt -> model.invoke -> 整理出处
    改一次 prompt 要改三个文件，容易漏。现在只改这里。

对外就一个类 RAGEngine，用法：
    from rag_engine import RAGEngine
    engine = RAGEngine()            # 启动时加载一次（读 index.faiss + 初始化模型）
    res = engine.ask("GPIO 最大电流？")
    print(res["answer"], res["sources"], res["seconds"])
"""

import time
from pathlib import Path

from dotenv import load_dotenv
from langchain_community.embeddings import ZhipuAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_deepseek import ChatDeepSeek


# ---------- 路径（沿用你项目里已验证的写法） ----------
# 本文件在 <项目根>/src/ 下：parents[0] = src，parents[1] = 项目根
ROOT = Path(__file__).resolve().parents[1]
STORE_DIR = ROOT / "vectorstore"

# 加载 .env 里的 DEEPSEEK_API_KEY / ZHIPUAI_API_KEY。
# 放在模块顶层，import 本文件时自动生效（和你原来的 api.py 风格一致）。
load_dotenv(ROOT / ".env")


# ---------- 可调参数 ----------
EMBED_MODEL = "embedding-3"    # 必须和建库时一致，换了会检索不到
LLM_MODEL = "deepseek-chat"
DEFAULT_K = 10                 # 默认检索块数，保持你原来的行为


# ---------- Prompt 模板（以后改口径只改这里） ----------
PROMPT_TEMPLATE = """你是一个芯片数据手册问答助手。请只根据下面提供的资料回答问题。
如果资料里没有答案，就直接说"数据手册中没有提到"，然后自己在网上搜素答案，寻找准确的答案，如果是正常聊天，就正常回复。

【资料】
{context}

【问题】
{question}

【回答】"""


class RAGEngine:
    """一次初始化，多次提问。"""

    def __init__(self,
                 store_dir: Path = STORE_DIR,
                 k: int = DEFAULT_K,
                 score_threshold: float | None = None):
        """
        store_dir        : 向量库目录（里面要有 index.faiss）
        k                : 每次检索几块
        score_threshold  : 相似度阈值。None = 不启用（保持旧行为）
                           传了值就先取 k*3 块、过滤掉距离过大的，再截前 k 块。
                           注意是 L2 距离，越小越相似，典型值 1.0~1.5，需要实验。
        """
        if not (store_dir / "index.faiss").exists():
            raise SystemExit(
                "没找到向量库，请先运行：.venv\Scripts\python src\p1_2_index.py"
            )

        self.k = k
        self.score_threshold = score_threshold

        self.embeddings = ZhipuAIEmbeddings(model=EMBED_MODEL)
        self.vectorstore = FAISS.load_local(
            str(store_dir),
            self.embeddings,
            allow_dangerous_deserialization=True,
        )
        self.model = ChatDeepSeek(model=LLM_MODEL, temperature=0)

    # ---------- 检索 ----------
    def _retrieve(self, question: str,
                  source: str | None = None,
                  k: int | None = None) -> list[Document]:
        """按问题取回最相关的块。source 传了就只查那一份手册。"""
        k = k or self.k

        # 指定了手册 -> 用 FAISS 的 metadata 过滤
        if source:
            return self.vectorstore.similarity_search(
                question, k=k, filter={"source": source}
            )

        # 启用了阈值 -> 多捞一些再过滤（直接按 k 块过滤可能剩不到 k 块）
        if self.score_threshold is not None:
            pairs = self.vectorstore.similarity_search_with_score(question, k=k * 3)
            return [doc for doc, score in pairs if score <= self.score_threshold][:k]

        return self.vectorstore.similarity_search(question, k=k)

    # ---------- 拼 prompt ----------
    @staticmethod
    def build_prompt(question: str, chunks: list[Document]) -> str:
        """把命中的原文和问题拼成一个完整的 prompt。"""
        context = "\n\n".join(c.page_content for c in chunks)
        return PROMPT_TEMPLATE.format(context=context, question=question)

    # ---------- 整理出处 ----------
    @staticmethod
    def format_sources(chunks: list[Document]) -> list[str]:
        """
        返回去重后的来源标签，如 "STM32F103C8_Datasheet.pdf 第 37 页"。

        用 list 而不是 set：set 的迭代顺序每次都不一样，
        同一个问题问两次、来源顺序会跳来跳去。
        """
        sources: list[str] = []
        for c in chunks:
            name = Path(c.metadata.get("source", "未知")).name
            ps = c.metadata.get("page_start")
            pe = c.metadata.get("page_end")
            if ps and pe and pe != ps:
                label = f"{name} 第 {ps}-{pe} 页"
            elif ps:
                label = f"{name} 第 {ps} 页"
            else:
                label = name
            if label not in sources:
                sources.append(label)
        return sources

    # ---------- 一次完整问答 ----------
    def ask(self, question: str,
            source: str | None = None,
            k: int | None = None) -> dict:
        """
        返回 dict：
            answer   模型回答（字符串）
            sources  来源标签列表（带页码）
            seconds  耗时（秒）
            chunks   命中的原始 Document（评测脚本要用它的 metadata 页码）
        """
        question = question.strip()
        if not question:
            raise ValueError("问题不能为空")

        start = time.time()

        chunks = self._retrieve(question, source=source, k=k)
        prompt = self.build_prompt(question, chunks)

        # 模型调用单独兜一层错：网络抖动/余额不足时给出可读的原因，
        # 而不是让整个 FastAPI 直接 500
        try:
            response = self.model.invoke(prompt)
        except Exception as e:
            raise RuntimeError(f"模型调用失败：{e}") from e

        return {
            "answer": response.content,
            "sources": self.format_sources(chunks),
            "seconds": round(time.time() - start, 2),
            "chunks": chunks,
        }
