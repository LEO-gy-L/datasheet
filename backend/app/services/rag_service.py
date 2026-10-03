# -*- coding: utf-8 -*-
"""
RAG 服务（检索 + 生成 的编排层）
================================
为什么要有这个文件：
    原来 chat.py / api.py / streamlit_app.py 里各有一份几乎一样的
        similarity_search -> 拼 prompt -> model.invoke -> 整理出处
    改一次 prompt 要改三个文件，容易漏。现在只改这里。

对外两个入口：

    RAGEngine        类     —— 一次初始化，多次提问。
                               评测脚本要自己指定 k 和阈值，所以用类。

    get_engine()     函数   —— 进程内全局唯一实例。
                               接口层用这个，避免每个请求都重建索引和模型。

用法：
    from backend.app.services.rag_service import RAGEngine, get_engine

    engine = get_engine()
    res = engine.ask("GPIO 最大电流？")
    print(res["answer"], res["sources"], res["seconds"])

依赖方向（很关键，避免循环 import）：
    本文件 -> config（配置）、retrieval/embeddings（向量化）、
              generation/llm（模型）、generation/prompts（措辞）、common/exceptions（异常）
    以上没有一个反过来 import 本文件。
"""
from __future__ import annotations

import time
from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

from backend.app.common.exceptions import (
    EmptyQuestionError,
    IndexNotFoundError,
    ModelCallError,
)
from backend.app.config import DEFAULT_K, DEFAULT_SCORE_THRESHOLD, STORE_DIR
from backend.app.generation.llm import get_llm
from backend.app.generation.prompts import PROMPT_TEMPLATE
from backend.app.retrieval.embeddings import get_embeddings


class RAGEngine:
    """一次初始化，多次提问。

    每个实例内部持有三样重东西：embeddings、FAISS 向量库、LLM 客户端。
    它们初始化要几秒，所以**不要在请求里 new**，见文件末尾的 get_engine()。
    """

    def __init__(self,
                 store_dir: Path = STORE_DIR,
                 k: int = DEFAULT_K,
                 score_threshold: float | None = DEFAULT_SCORE_THRESHOLD):
        """
        store_dir        : 向量库目录（里面必须有 index.faiss）
        k                : 每次检索几块
        score_threshold  : 相似度阈值。None = 不启用（保持旧行为）
                           传了值就先取 k*3 块、过滤掉距离过大的，再截前 k 块。
                           注意这是 L2 距离，**越小越相似**，典型值 1.0~1.5，需要实验。
        """
        if not (store_dir / "index.faiss").exists():
            # 抛自定义异常而不是 SystemExit：
            # SystemExit 是"退出进程"的信号，被 try/except Exception 抓不到，
            # 会让调用方（尤其是 Web 服务）很难优雅处理。异常类型见 common/exceptions.py
            raise IndexNotFoundError(
                "没找到向量库，请先在项目根目录运行："
                "python -m backend.app.ingestion.indexer"
            )

        self.k = k
        self.score_threshold = score_threshold

        self.embeddings = get_embeddings()
        self.vectorstore = FAISS.load_local(
            str(store_dir),
            self.embeddings,
            # allow_dangerous_deserialization：FAISS 本地库用 pickle 反序列化，
            # 官方默认禁止（怕加载到恶意文件）。这里库是你自己生成的，所以打开。
            allow_dangerous_deserialization=True,
        )
        self.model = get_llm()

    # ------------------------------------------------------------ 检索
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

        # 启用了阈值 -> 先多捞一些再过滤
        # （直接按 k 块过滤的话，可能过滤完剩不到 k 块，甚至一块不剩）
        if self.score_threshold is not None:
            pairs = self.vectorstore.similarity_search_with_score(question, k=k * 3)
            return [doc for doc, score in pairs if score <= self.score_threshold][:k]

        return self.vectorstore.similarity_search(question, k=k)

    # ------------------------------------------------------------ 拼 prompt
    @staticmethod
    def build_prompt(question: str, chunks: list[Document]) -> str:
        """把命中的原文和问题拼成一个完整的 prompt。

        模板在 generation/prompts.py，改措辞去那里。
        """
        context = "\n\n".join(c.page_content for c in chunks)
        return PROMPT_TEMPLATE.format(context=context, question=question)

    # ------------------------------------------------------------ 整理出处
    @staticmethod
    def format_sources(chunks: list[Document]) -> list[str]:
        """
        返回去重后的来源标签，例如 "STM32F103C8_Datasheet.pdf 第 37 页"。

        为什么用 list 而不是 set：
            set 的迭代顺序每次都不一样（Python 的哈希随机化），
            同一个问题问两次、来源顺序会跳来跳去，看起来像不稳定。
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

    # ------------------------------------------------------------ 一次完整问答
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
            raise EmptyQuestionError("问题不能为空")

        start = time.time()

        chunks = self._retrieve(question, source=source, k=k)
        prompt = self.build_prompt(question, chunks)

        # 模型调用单独兜一层：网络抖动 / 余额不足时给出可读原因，
        # 而不是让整个 FastAPI 直接 500（原始异常信息对用户毫无意义）
        try:
            response = self.model.invoke(prompt)
        except Exception as e:
            raise ModelCallError(f"模型调用失败：{e}") from e

        return {
            "answer": response.content,
            "sources": self.format_sources(chunks),
            "seconds": round(time.time() - start, 2),
            "chunks": chunks,
        }


# ---------------------------------------------------------------- 单例
# 这里用"模块级变量"而不是 @lru_cache，原因：
#     lru_cache 在"构造函数抛异常"这条路径上的行为不直观（异常不会被缓存，
#     下次调用会重试），而显式写个全局变量，读代码的人一眼就懂。
_engine: RAGEngine | None = None


def get_engine() -> RAGEngine:
    """返回进程内唯一的引擎实例。

    第一次调用时创建（几秒），之后每次调用立刻返回同一份。
    main.py 在服务启动时调用一次，等于提前把索引和模型加载进内存。
    """
    global _engine
    if _engine is None:
        _engine = RAGEngine()
    return _engine
