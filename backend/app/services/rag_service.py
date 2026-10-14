# -*- coding: utf-8 -*-
"""
RAG 服务（检索 + 生成 的编排层）
================================
为什么要有这个文件：
    原来 chat.py / api.py / streamlit_app.py 里各有一份几乎一样的
        similarity_search -> 拼 prompt -> model.invoke -> 整理出处
    改一次 prompt 要改三个文件，容易漏。现在只改这里。

【2026-10-03 改造：检索从"单路向量"换成"混合检索"】

    以前：question -> embeddings -> FAISS.similarity_search -> 拼 prompt
    现在：question -> HybridRetriever（BM25 + 向量 -> RRF -> 重排 -> 父块放大）
                  -> 拼 prompt -> model.invoke

    检索的全部细节都封在 retrieval/hybrid.py 里，本文件**不再关心**
    到底走了几条路、融合分怎么算 —— 它只要一句：
        "把问题给我，还我几个最该送给模型的块"

    这就是分层的价值：以后再加一路检索（比如按章节标题的元数据过滤），
    只改 hybrid.py，本文件和接口层一行都不用动。

    本文件比旧版多做的两件事：
      ① build_prompt 给每个片段加上 [片段N · 类型 · 出处] 标签头，
         让模型能说清"这条来自第几页"，也便于它引用编号；
      ② ask() 的返回值多了一个 trace 字段，装着检索的完整诊断信息
         （两路各召回了什么、RRF 融合分、重排前后排序）。
         接口层不返回它（response_model 会过滤掉），但评测脚本和
         CLI 调试要的就是它 —— "答案是错的"到底是检索没捞到，
         还是捞到了却被排序挤掉，看 trace 一眼就知道。

对外两个入口：

    RAGEngine        类     —— 一次初始化，多次提问。
                               评测脚本要自己指定 k，所以用类。

    get_engine()     函数   —— 进程内全局唯一实例。
                               接口层用这个，避免每个请求都重建索引和模型。

用法：
    from backend.app.services.rag_service import RAGEngine, get_engine

    engine = get_engine()
    res = engine.ask("GPIO 最大电流？")
    print(res["answer"], res["sources"], res["seconds"])

依赖方向（很关键，避免循环 import）：
    本文件 -> config（配置）、retrieval/hybrid（混合检索）、
              generation/llm（模型）、generation/prompts（措辞）、common/exceptions（异常）
    以上没有一个反过来 import 本文件。
"""
from __future__ import annotations

import time
from pathlib import Path

from langchain_core.documents import Document

from backend.app.common.exceptions import (
    EmptyQuestionError,
    IndexNotFoundError,
    ModelCallError,
)
from backend.app.config import RERANK_TOP_N, STORE_DIR
from backend.app.generation.llm import get_llm
from backend.app.generation.prompts import PROMPT_TEMPLATE
from backend.app.retrieval.hybrid import HybridRetriever, get_retriever

# 块类型 -> 给大模型看的中文标签。
# 为什么要翻译成中文：
#   prompt 是中文的，里面混着 "parent:table" 这种内部代号，模型理解起来更费劲，
#   而且容易在回答里把代号念出来（"根据 parent:table 片段……"），很难看。
_KIND_LABEL = {
    "table": "表格",
    "text": "正文",
    "figure": "图形指针",
}


def _kind_label(raw_type: str) -> str:
    """把 "parent:table" 这种带前缀的类型名，翻译成 "表格"。"""
    # split(":", 1)[-1] 取冒号后面那一段：
    #   "parent:table" -> "table"；"table" -> "table"（没冒号时原样返回）
    base = raw_type.split(":", 1)[-1]
    return _KIND_LABEL.get(base, base or "资料")


class RAGEngine:
    """一次初始化，多次提问。

    每个实例内部持有两样重东西：混合检索器（含 BM25 索引、FAISS 向量库）
    和 LLM 客户端。它们初始化要几秒，所以**不要在请求里 new**，
    见文件末尾的 get_engine()。
    """

    def __init__(self,
                 store_dir: Path = STORE_DIR,
                 k: int = RERANK_TOP_N,
                 score_threshold: float | None = None):
        """
        store_dir        : 向量库目录（里面必须有 docs.jsonl；
                           还有 index.faiss 时语义路才可用）
        k                : **最终送给大模型的块数**（重排之后取前 k 块）。
                           旧参数名沿用下来是为了不改脚本调用，
                           但语义已经变了：以前是"向量检索取 k 块"，
                           现在是"混合检索+重排之后取 k 块"。
                           默认 RERANK_TOP_N = 3。
        score_threshold  : 【已废弃】旧版用 L2 距离做阈值过滤。
                           混合检索的融合分是排名折算出来的（1/(60+名次)），
                           没有"绝对距离"这个概念，没法再套一个固定阈值。
                           参数留着只是为了不破坏老脚本的调用签名，
                           传了也不起作用 —— 如果哪天看到它，请直接删掉调用。
        """
        if score_threshold is not None:
            # 不静默忽略 —— 本项目的硬规矩是"不悄悄丢东西"。
            # 但也不抛异常（会让老脚本直接跑不起来），打一行提示就够了。
            print("[提示] score_threshold 在混合检索下已失效，本次调用忽略该参数。")

        self.k = k

        # 检索器：默认目录走全局单例，换目录时单独建一个。
        #
        # 为什么要判断目录：
        #   get_retriever() 里面的单例是按 STORE_DIR 建的。
        #   如果评测时想换一个库（RAGEngine(store_dir=别的目录)），
        #   复用那个单例就会读到错的库 —— 而且不报错，只是答案莫名不对。
        #   所以非默认目录必须自己新建实例。
        try:
            if Path(store_dir) == Path(STORE_DIR):
                self.retriever = get_retriever()
            else:
                self.retriever = HybridRetriever(store_dir=store_dir)
        except FileNotFoundError as e:
            # 检索层抛的是 FileNotFoundError（找不到 docs.jsonl），
            # 接口层认识的却是 IndexNotFoundError。
            # 转换在这一层做 —— 让"业务异常"在 service 边界统一，
            # 上层（api/chunks）就不用认识 Python 内置异常了。
            raise IndexNotFoundError(str(e)) from e
        except ValueError as e:
            raise IndexNotFoundError(str(e)) from e

        self.model = get_llm()

    # ------------------------------------------------------------ 检索
    def _retrieve(self, question: str,
                  source: str | None = None,
                  k: int | None = None) -> tuple[list[Document], dict]:
        """按问题取回最相关的块。

        返回 (块列表, 完整诊断)。source 传了就只查那一份手册。

        和旧版最大的区别：旧版是"一次向量检索 + 可选阈值过滤"，
        现在是"两路召回 -> RRF -> 重排 -> 父块放大"一条完整链路。
        那 10 多行细节全在 hybrid.retrieve() 里，这里只挑结果。
        """
        trace = self.retriever.retrieve(question, source=source, top_n=k or self.k)
        return trace["docs"], trace

    # ------------------------------------------------------------ 拼 prompt
    @staticmethod
    def build_prompt(question: str, chunks: list[Document]) -> str:
        """把命中的原文和问题拼成一个完整的 prompt。

        每块前面加一个标签头：

            [片段1 · 表格 · CH32F103_Datasheet_CN.pdf 第 2 页 · 表1-1 CH32F103x 产品资源分配]
            | 产品型号 / 资源差异 | CH32F103 C6T6 | ...
            | 芯片引脚数 | 48 | ...
            | 闪存（字节） | 32K | ...
            ...

        为什么非要加这个头（而不是直接把原文堆进去）：
            ① 让模型能引用页码。不加头的话，模型想说"来自第 2 页"只能靠猜。
            ② 标明类型。图形块只是指针，标了"图形指针"之后模型才不会
               把"本页含引脚图"当成"引脚排布是这样的"。
            ③ 片段编号让排查变简单。答案不对时可以直接问"你用的是片段几"。

        模板本身在 generation/prompts.py，改措辞去那里，别改这里。
        """
        parts: list[str] = []
        for i, c in enumerate(chunks, 1):
            m = c.metadata
            name = Path(m.get("source") or "未知").name
            kind = _kind_label(str(m.get("type", "")))

            ps, pe = m.get("page_start"), m.get("page_end")
            if ps and pe and pe != ps:
                page = f"第 {ps}-{pe} 页"
            elif ps:
                page = f"第 {ps} 页"
            else:
                page = "页码未知"

            title = (m.get("title") or "").strip()
            loc = f"{name} {page}" + (f" · {title}" if title else "")

            parts.append(f"[片段{i} · {kind} · {loc}]\n{c.page_content}")

        context = "\n\n".join(parts)
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
            trace    检索的完整诊断（两路召回 / 融合 / 重排 / 打包），
                     接口层不返回它，但调试"答案为什么不对"时必看
        """
        question = question.strip()
        if not question:
            raise EmptyQuestionError("问题不能为空")

        start = time.time()

        chunks, trace = self._retrieve(question, source=source, k=k)
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
            "trace": trace,
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


def reset_engine() -> None:
    """丢掉单例，让下次调用重新创建（连带重新加载检索器）。

    【2026-10-03 新增，配合网页端"入库"功能】

    调用时机只有一个：**向量库的内容变了之后**（新建库 / 删除文档）。
    引擎内部持有检索器（BM25 索引 + FAISS 向量库），而这些都是
    "启动时读一次、之后吃内存"的东西 —— 磁盘变了它不会自己知道。

    ⚠️ 注意它和 hybrid.reset_retriever() 的关系：
        RAGEngine.__init__ 里走的 `get_retriever()` 也是同一个单例，
        所以理论上清掉 _engine 之后重建，还是会拿到**旧的那个检索器**。
        两个都要重置才真的生效。services/indexing_service.py 里的
        `_reload_engine()` 就是按顺序调这两个 —— 别只调一个。
    """
    global _engine
    _engine = None
