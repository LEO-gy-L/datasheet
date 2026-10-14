# -*- coding: utf-8 -*-
"""
混合检索：BM25 + 向量 → RRF 融合 → 重排 → 父块放大
==================================================

【一句话说清这个文件在干嘛】

    以前检索只有一条路：把问题向量化，去 FAISS 里找最近的几块。
    问题是"最近"不等于"对" —— 用户问 "CH32F103C6T6 的引脚数"，
    纯向量检索可能给你一篇讲"引脚功能复用"的正文，因为语义相近；
    而真正答案所在的那张资源分配表，因为全是数字和短词，
    向量表达不出来，排在十几名开外。

    解法不是换一个更好的向量模型，而是**多找几条路，然后把几条路
    的结果合并投票**。这就是"混合检索"（Hybrid Retrieval）。

【完整链路（对应 config.py 里的那几个旋钮）】

    用户问题
       │
       ├──────────────┬──────────────┐
       ▼              ▼              │
  ①「语义路」    ①「关键词路」       │  RETRIEVAL
   向量检索         BM25            │
   召回 10 条      召回 10 条        │  RECALL_DENSE=10
       │              │              │  RECALL_BM25=10
       └──────┬───────┘              │
              ▼                      │
  ②     RRF 倒数排名融合              │  RRF_K=60
       两条路的排名折算成统一分值       │
       去重后取前 10 条               │  FUSED_TOP=10   ← 你说的"召回 10 个块"
              │                      │
              ▼                      │
  ③     重排（智谱 rerank 模型）       │  RERANK_TOP_N=3
       对这 10 条逐条打分，重新排序     │
       取分数最高的 3 条               │  ← 你说的"打分，取最高的 3 块"
              │                      │
              ▼                      │
  ④      父块放大                    │  EXPAND_PARENT
       命中一个碎片，就把碎片所在的     │
       整个章节 / 整张表一起捞出来     │  ← 你说的"以及所在的大块"
              │                      │
              ▼                      │
      打包 → 交给大模型生成答案        │  GENERATION
                                     │
  ───────────────────────────────────┘

【为什么每条路都要，光有一条不行】

    向量路（dense）擅长什么：
        语义相近。用户写"芯片跑多快"，文档写"CPU 主频 72MHz"，
        字面一个字都不一样，向量能把它们拉到一起。

    向量路栽在哪：
        表格里的孤立数字（48 / 32K / 10K）和型号串（CH32F103C6T6），
        向量化之后彼此极其相似 —— 整个向量空间里"48"和"32K"挤在一团，
        分不出哪个数字属于哪个型号。

    关键词路（BM25）擅长什么：
        精确字面匹配。"CH32F103C6T6" 这个串，BM25 就是按这个串去找，
        找到了就是找到了，不含糊。

    关键词路栽在哪：
        换个说法就找不到。"芯片跑多快" 里没有"主频"两个字，BM25 抓瞎。

    所以：一个管"意思对"，一个管"字面对"，合起来才稳。

【为什么用 RRF 融合，而不是把两边的分数加权平均】

    两边的分数量纲完全不同，根本没法直接相加：
        - 向量路给的是 L2 距离，范围 0~2 左右，**越小越好**
        - BM25 给的是 relevance 分，范围 0~几十，**越大越好**
    强行归一化再相加，等于拍脑袋定权重（0.5 : 0.5？0.7 : 0.3？），
    换个问题这个权重就不合适了。

    RRF 绕开这个问题 —— **只用排名，不用分数**：

        RRF 分值(文档) = Σ    1 / (RRF_K + 这个文档在那条路上的名次)
                       各路

    举例（RRF_K = 60）：

        某块在向量路排第 1、BM25 路排第 8
            → 1/(60+1) + 1/(60+8) = 0.01639 + 0.01471 = 0.03110

        另一块在两条路都排第 3
            → 1/(60+3) + 1/(60+3) = 0.01587 + 0.01587 = 0.03174   ← 更高

    这一条式子就是 RRF 的全部精髓：**两条路都认可的东西，胜过一次第一**。
    它自动实现了"投票"的效果，而且不需要知道任何一方的分数长什么样。
    RRF_K = 60 是原论文（Cormack et al. 2009）的实验推荐值 ——
    它的作用是压一压"排第 1"的绝对优势，让第 2、3 名也能贡献分数，
    避免某一条路的一家之言直接决定结果。

【为什么叫"父块放大"，不直接检索大块】

    这是个两难：
        块切得大 → 语义糊成一团，检索不准（一整节里什么都提了一点，什么都不突出）
        块切得小 → 检索准，但命中之后只有半句话，模型看不懂上下文

    答案是**两层结构**：
        检索用小块（子块，200~500 字），因为小块语义聚焦、检索准
        送模型用大块（父块，一整节 / 一整张表），因为大块上下文完整

    切块阶段（ingestion/chunking.py）已经把每个子块归到了它的父块
    （chunks.jsonl 里的 parent_id 字段），这里检索命中后按 parent_id
    去 parents.json 里取回完整内容即可。

【对外接口】

    get_retriever()            进程内唯一的检索器（和 rag_service.get_engine 一个套路）
    HybridRetriever.search()   问题 -> list[Document]（直接给 rag_service 用）
    HybridRetriever.retrieve() 问题 -> 完整诊断字典（看每路召回了什么、各拿多少分）

命令行自测（不依赖 rag_service，可以单独跑）：

    python -m backend.app.retrieval.hybrid "CH32F103C6T6 的引脚数是多少"
    python -m backend.app.retrieval.hybrid "引脚数" --no-rerank      # 看融合后的原始排序
    python -m backend.app.retrieval.hybrid "GPIO 电流" --source CH32F103_Datasheet_CN.pdf
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import requests
from langchain_core.documents import Document

from backend.app.config import (
    BM25_B,
    BM25_K1,
    EXPAND_PARENT,
    FIGURE_SCORE_PENALTY,
    FUSED_TOP,
    RECALL_BM25,
    RECALL_DENSE,
    RERANK_ENABLED,
    RERANK_MAX_DOC_CHARS,
    RERANK_MODEL,
    RERANK_RETURN_RAW,
    RERANK_SOURCE,
    RERANK_TIMEOUT,
    RERANK_TOP_N,
    RERANK_URL,
    RRF_K,
    STORE_DIR,
)


# ==================================================================
# 一、分词：中英混排怎么切成 BM25 能用的 token
# ==================================================================

# BM25 是"词袋"模型 —— 它把一段文字打散成一堆 token，只看 token 出现没出现、
# 出现几次，完全不看顺序。所以"怎么切"直接决定了检索的好坏。
#
# 切法（不引入 jieba 这类分词库，自己用正则扫）：
#   ① 拉丁字母/数字串 —— 整个算一个 token
#         "CH32F103C6T6" -> ch32f103c6t6
#         "Cortex-M3"    -> cortex-m3        （连字符保留，因为它是型号的一部分）
#         "2.7V"         -> 2.7v             （小数点保留，因为它是数值的一部分）
#         "SMBus/PMBus"  -> smbus + pmbus    （斜杠不保留，让两个外设名各自成词）
#   ② 连续的汉字串 —— 拆成「单字」+「相邻双字（bigram）」
#         "定时器" -> 定, 时, 器, 定时, 时器
#
# 为什么汉字要拆成单字 + 双字：
#   中文没有空格，一个"词"到底是"定时"+"器"还是"定"+"时器"，机器不知道。
#   最常见的工程做法是"双字切分"（bigram）：不管词边界，两两相邻切一刀。
#   "定时器" 变成 定时 + 时器，用户问"定时器"时必然命中。
#
#   那为什么还保留单字？
#   因为有些查询很短 —— 用户就问"功耗"两个字。如果库里写的是"低功耗模式"，
#   bigram 切出来是 低功 + 功耗 + 耗模 + 模式，"功耗"这个 bigram 恰好命中；
#   但假如用户问"耗电"，bigram 切出"耗电"，库里没有这个词，就漏了。
#   保留单字能让"耗"这个字匹配上"低功耗"，兜住这种漏召回。
#
#   单字会引入"的/是/在"这类噪声吗？
#   会，但影响很小 —— BM25 的 IDF 项会自动压低它们。一个词出现在几乎所有
#   文档里，它的 IDF 趋近于 0，等于自动被忽略。这是 BM25 自带的降噪机制。
#
# 字符类里 - 和 + 放在末尾/中间都是字面量（不用转义），. 在字符类里也是字面量。
_TOKEN_SCAN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*|[\u4e00-\u9fff]+")


def tokenize(text: str) -> list[str]:
    """把一段中英混排的文字切成 BM25 用的 token 列表。

    这是整个检索层最底层的函数 —— 建索引时用它切文档，
    查询时用它切问题，**两边必须用同一个函数**，否则切法不一致就永远匹配不上。
    """
    tokens: list[str] = []

    # finditer 按出现顺序扫出所有"拉丁串"和"汉字串"，其余字符（空格、标点、
    # 括号、竖线等）会被自动跳过 —— 相当于天然的分隔符。
    for m in _TOKEN_SCAN_RE.finditer(text):
        s = m.group()

        # str.isascii()：这个字符串是不是全由 ASCII 字符组成。
        # 拉丁串（字母/数字）为 True，汉字串为 False —— 用它区分两类。
        if s[0].isascii():
            # 拉丁词统一转小写，这样 "GPIO"、"gpio"、"Gpio" 是同义词。
            tokens.append(s.lower())
            continue

        # ---- 汉字串 ----
        tokens.extend(s)                        # 单字："定时器" -> 定, 时, 器
        for i in range(len(s) - 1):             # 双字："定时器" -> 定时, 时器
            tokens.append(s[i:i + 2])

    return tokens


# ==================================================================
# 二、BM25：关键词检索的经典算法（自己实现，零新依赖）
# ==================================================================

class BM25Index:
    r"""Okapi BM25 索引。

    【公式】

        score(问题, 文档) = Σ          IDF(词) * 词频(词, 文档) * (k1 + 1)
                           词∈问题    ─────────────────────────────────────
                                      词频 + k1 * (1 - b + b * 文档长度/平均长度)

    【三项分别是什么】

    ① IDF（逆文档频率）—— 决定"这个词有多值钱"
           IDF(词) = ln( (N - n + 0.5) / (n + 0.5) + 1 )

           N = 文档总数，n = 含这个词的文档数。
           一个词出现在越少的文档里，它越有辨识度，IDF 越大。
           "定时器" 只在 3 篇文档里出现 -> IDF 大，命中它说明找对了。
           "数据" 在 100 篇文档里都有 -> IDF 接近 0，命中它等于没命中。
           末尾那个 +1 是"BM25+"修正，保证 IDF 永远为正数（不会出现负分）。

    ② 词频饱和 —— 决定"同一个词重复出现，收益有多大"
           分子有 (k1+1)*tf，分母有 tf —— 于是 tf 越大，整个分数越接近
           (k1+1)，但永远超不过。这叫**饱和**。
           一个词出现 10 次和出现 100 次，分数差不了多少 ——
           这很合理：一篇文章里"定时器"出现 10 次，已经足够证明它讲定时器了，
           再提 90 次也不该让它分数翻 10 倍（那叫关键词堆砌）。
           k1 控制饱和的快慢：k1 越小越快饱和。默认 1.5。

    ③ 长度归一化 —— 决定"长文档要不要打折"
           长文档天然容易命中更多词（词多嘛），不打折对短文档不公平。
           分母里 b * 文档长度/平均长度 就是这个折扣。
           b=0：完全不打折（长文档占便宜）
           b=1：完全按长度打折
           默认 b=0.75 —— 打七五折。既不忽视长度，也不让长度说了算。

    【为什么自己写而不用 rank_bm25 库】

        rank_bm25 的核心代码也就几十行，但它的 tokenizer 默认是 str.split()
        ——按空格切。中文没有空格，一整句会被切成一个 token，完全不可用。
        所以无论用不用它，我们**都必须自己写 tokenizer**。
        既然 tokenizer 要自己写，BM25 的主体也就顺带自己实现了：
        少一个第三方依赖，公式还全摆在眼前，调参时知道自己在动什么。
    """

    def __init__(self,
                 doc_tokens: list[list[str]],
                 k1: float = BM25_K1,
                 b: float = BM25_B) -> None:
        """
        doc_tokens : 每篇文档的 token 列表，即 [tokenize(文档1), tokenize(文档2), ...]
        k1         : 词频饱和参数（见类文档 ②）
        b          : 长度归一化强度（见类文档 ③）
        """
        self.k1 = k1
        self.b = b
        self.n_docs = len(doc_tokens)

        # 每篇文档的长度（token 个数）—— 长度归一化要用
        self.doc_len: list[int] = [len(t) for t in doc_tokens]

        # 平均文档长度 —— 长度归一化的基准线
        self.avg_len: float = (sum(self.doc_len) / self.n_docs) if self.n_docs else 0.0

        # ---- 倒排表（inverted index）----
        # 结构：{token: {文档下标: 这个词在该文档里出现几次}}
        #   "定时器" -> {3: 2, 17: 1}   表示第 3 篇出现 2 次、第 17 篇出现 1 次
        #
        # 为什么用倒排表而不是"逐篇文档扫描"：
        #   逐篇扫描是 O(文档数 × 问题词数)；倒排表只看"真的有这个词的文档"，
        #   是 O(命中文档数)。现在只有 100 多块，差别看不出来，
        #   但将来换成几万块的库，这个差别就是秒级和分钟级的区别。
        self.postings: dict[str, dict[int, int]] = {}
        for i, toks in enumerate(doc_tokens):
            # Counter 数出每个 token 出现几次（这就是词频 tf）
            for tok, tf in Counter(toks).items():
                self.postings.setdefault(tok, {})[i] = tf

        # ---- 预先把每个 token 的 IDF 算好 ----
        # 建索引时算一次，查询时直接查表 —— 避免每次查询重复做 log 运算。
        # len(p) 就是公式里的 n（含这个词的文档数）。
        self.idf: dict[str, float] = {
            tok: math.log((self.n_docs - len(p) + 0.5) / (len(p) + 0.5) + 1.0)
            for tok, p in self.postings.items()
        }

    def scores(self, query_tokens: list[str]) -> dict[int, float]:
        """算出每篇文档对这个问题的 BM25 分。返回 {文档下标: 分数}。

        只返回分数 > 0 的文档 —— 一个词都没命中的文档直接不出现在结果里，
        等于天然的过滤（比先算全部再筛掉更快、更省内存）。
        """
        out: dict[int, float] = {}

        # set(...) 去重：问题里同一个词写了两遍，不应该算两次分。
        # （标准 BM25 有两种做法：乘查询词频 or 只算一次。这里选后者，更常见也更稳。）
        for tok in set(query_tokens):
            idf = self.idf.get(tok)
            if idf is None:
                continue        # 词典里没这个词（比如问题里冒出来个生僻型号）—— 跳过

            for doc_i, tf in self.postings[tok].items():
                # 长度归一化项：(1 - b + b * 文档长度 / 平均长度)
                # avg_len 为 0 只可能发生在"一篇文档都没有"时，那时压根进不到这里，
                # 但还是防一手，避免 ZeroDivisionError 把整个接口搞崩。
                norm = 1.0 - self.b + self.b * (
                    self.doc_len[doc_i] / self.avg_len if self.avg_len else 1.0
                )
                out[doc_i] = out.get(doc_i, 0.0) + idf * tf * (self.k1 + 1) / (tf + self.k1 * norm)

        return out

    def top_n(self, query_tokens: list[str], n: int) -> list[tuple[int, float]]:
        """取分最高的 n 篇。返回 [(文档下标, 分数)]，按分数从高到低。"""
        scored = self.scores(query_tokens)
        # 排序键写成 (-分数, 下标)：分数降序；分数相同时按下标升序。
        # 加第二个键是为了**结果稳定** —— 分数打平时如果顺序每次都不一样，
        # 同一问题问两遍会看到不同的来源顺序，排查问题时极其误导。
        return sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))[:n]


# ==================================================================
# 三、读盘：把 indexer.py 落下的两个文件读进内存
# ==================================================================

@dataclass
class Chunk:
    """一个检索单元（子块）。

    这是从 vectorstore/docs.jsonl 里读出来的一行。
    分「index_text」和「content」两份文字，是这次改造的核心设计：

        index_text : 拿去**检索**的（表格块是自描述句，正文块是正文本身）
                     "CH32F103 C6T6 · 芯片引脚数 = 48"
        content    : 拿去**展示 / 送模型**的原文（markdown 表格 / 带标题的正文）
                     "| 产品型号/资源差异 | CH32F103 C6T6 | ... | 48 | ..."
    """
    idx: int                 # 在本列表里的位置（BM25 / RRF 都靠它定位）
    id: str                  # 块 id，如 CH32F103_Datasheet_CN_c0003
    index_text: str          # 检索用文本
    content: str             # 原文（展示 / 送模型）
    source: str              # 手册文件名
    type: str                # text / table / figure
    title: str               # 章节路径 或 表格标题
    page_start: int
    page_end: int
    parent_id: str           # 所属父块 id（空串表示没有父块）


# 正文块和图形块的 index_text 前面带有这么一行标签：
#     [CH32F103_Datasheet_CN.pdf 第 1 页 · 正文]
# 这行里含**手册文件名**，而它出现在**每一个**正文块里。
# 直接拿去建 BM25 索引的后果：所有块都含 "ch32f103"、"datasheet"、"正文" 这些 token，
# 它们的文档频率 n ≈ N，IDF ≈ 0，白白占了索引空间（更糟的是如果哪天文件名恰好
# 是用户查询的一部分，会造成一堆无意义的命中）。
# 所以建索引和重排之前，先把这行标签剥掉。
_INDEX_HEADER_RE = re.compile(r"^\[[^\]\n]{0,200}\]\s*")


def strip_index_header(text: str) -> str:
    r"""剥掉 index_text 开头那一行 ``[文件名 第N页 · 类型]`` 标签。

    只剥**开头第一处**，而且限定方括号里不超过 200 字符、不含换行 ——
    这样正文里正常出现的方括号（比如 "[1] 参考手册" 这种脚注）不会被误伤。

    表格块的 index_text 以 "表格标题: " 开头，压根不匹配这个正则，天然安全。
    """
    return _INDEX_HEADER_RE.sub("", text, count=1)


def load_chunks(store_dir: Path = STORE_DIR) -> list[Chunk]:
    """读 vectorstore/docs.jsonl（建库时由 indexer.py 落下的扁平语料）。

    为什么单独落一份 docs.jsonl，不直接从 FAISS 的 pkl 里读：
        FAISS 的 index.pkl 是它自己的内部格式（pickle + 一堆 Docstore 包装），
        反查起来又绕又脆。扁平 JSONL 一行一块，肉眼可读、
        用 jq / 记事本都能直接查，出问题时一眼就能看出是数据错了还是算法错了。
    """
    path = Path(store_dir) / "docs.jsonl"
    if not path.exists():
        raise FileNotFoundError(
            f"找不到 {path}。请先建库（不用花钱的那一步就够）：\n"
            f"    python -m backend.app.ingestion.indexer --bm25-only"
        )

    chunks: list[Chunk] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            chunks.append(Chunk(
                idx=len(chunks),                       # 位置就是它在文件里的行号（从 0 数）
                id=d.get("id", ""),
                index_text=d.get("index_text", "") or d.get("content", ""),
                content=d.get("content", ""),
                source=d.get("source", ""),
                type=d.get("type", ""),
                title=d.get("title", ""),
                page_start=int(d.get("page_start") or 0),
                page_end=int(d.get("page_end") or 0),
                parent_id=d.get("parent_id", ""),
            ))
    return chunks


def load_parents(store_dir: Path = STORE_DIR) -> dict[str, dict]:
    """读 vectorstore/parents.json（父块表）。

    结构：{parent_id: {"content": 整节/整表的原文, "child_ids": [...], ...}}
    服务启动时一次性读进内存，之后按 parent_id 取是 O(1) —— 一次字典查找。
    """
    path = Path(store_dir) / "parents.json"
    if not path.exists():
        return {}          # 没有父块表不算错，退化成"只送命中的子块"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


# ==================================================================
# 四、RRF：把几条路的排名融合成一个分数
# ==================================================================

def rrf_fuse(rankings: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    r"""Reciprocal Rank Fusion —— 倒数排名融合。

        score(文档) = Σ    1 / (k + 该文档在这条路上的名次)
                     各路

    参数：
        rankings : 每一条路的召回结果，**必须是排好序的**（下标列表，
                   越靠前越相关）。比如 [[3, 17, 5, ...], [17, 2, 3, ...]]
                   代表"向量路召回顺序"和"BM25 路召回顺序"。
        k        : 平滑常数，默认 60（原论文推荐值）。

    为什么名次要 +1：
        名次从 1 开始数。如果从 0 开始，排第一的文档拿到 1/(60+0)，
        而"排第一"和"排第二"的差距会被放大，k 的平滑作用就弱了。

    返回值：{文档下标: 融合分}，**没有排序**，调用方自己 sort
            （因为调用方可能还想按别的规则打平局）。
    """
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, doc_idx in enumerate(ranking, start=1):
            fused[doc_idx] = fused.get(doc_idx, 0.0) + 1.0 / (k + rank)
    return fused


# ==================================================================
# 五、重排：调智谱 rerank 接口，对候选池逐条打分
# ==================================================================

def zhipu_rerank(query: str,
                 documents: list[str],
                 top_n: int,
                 timeout: float = RERANK_TIMEOUT) -> list[tuple[int, float]] | None:
    """调用智谱 rerank 接口对候选重新打分。

    【它和向量检索、BM25 有什么本质不同】

        BM25 是"字面匹配" —— 一个词一个字地对。
        向量检索是"双塔" —— 问题和文档**各自**先编码成向量，再比距离。
            编码时问题和文档互相看不见，所以叫"双塔"。

        rerank 是"交叉编码"（cross-encoder）——
        把 (问题, 候选文档) **拼在一起**送进模型，让模型逐字读一遍，
        直接输出一个相关性分数。因为能看到两者之间的细节对应关系，
        精度显著高于前两者，代价是慢（每条候选都要单独跑一次模型推理）。

        所以它的位置是"精排"：前两路负责从 100 多块里粗筛出 10 个候选，
        rerank 负责在这 10 个里排出真正的前 3。粗筛要快要全，精排要准。

    【参数】
        query     : 用户问题
        documents : 候选文字列表（调用方决定传 index_text 还是 content）
        top_n     : 要返回前几名

    【返回】
        成功：[ (候选在 documents 里的下标, 相关性分数) ]，按分数降序
        失败：None（**不抛异常**）

    【return_raw_scores 这个参数很关键，实测算过才知道】

        智谱默认返回的 relevance_score 是 sigmoid 归一化后的值，会**饱和在 0.99~1.0**。
        同一批 10 条候选，两种模式对比：

            默认（归一化）            return_raw_scores=True（原始分）
            -------------------      ----------------------------
            1.00000000  图形块 p11     24.27  表格块「表1-1」← 答案在这
            1.00000000  图形块 p4      18.23  图形块 p3
            1.00000000  图形块 p3      18.16  图形块 p11
            1.00000000  正文  p23      18.13  图形块 p4
            1.00000000  表格块 表1-1   17.28  正文  p23

        左列所有分数都是 1.00000000，排序完全由小数点后第 7 位决定 ——
        那已经不是"打分"了，是噪声。结果就是"引脚图"压过"引脚数"，
        含答案的表格块被挤出 Top-3。
        右列区分度清晰，排序完全正确。

        所以 config.RERANK_RETURN_RAW 默认 True，且**不该改**。

    【为什么失败要返回 None 而不是抛异常】

        rerank 是"锦上添花"的一步，不是必需的一步。
        网络超时、余额不足、接口改版 —— 任何一种都不应该让用户拿不到答案。
        返回 None 后调用方会退回用 RRF 的顺序，答案照样出得来，
        只是排序精度差一点。这叫**优雅降级**。
        注意：接口返回的 index 是"在 documents 里的下标"（从 0 开始），
        **不是**文档 id，调用方必须自己映射回去。
    """
    key = os.getenv("ZHIPUAI_API_KEY", "").strip()
    if not key or "在这里填" in key:
        return None

    payload = {
        "model": RERANK_MODEL,
        "query": query[:4000],                      # 接口限制 query 最长 4096 字符
        # 单条候选截断：接口限制单条 4096 字符，这里留足余量取 1200。
        # 为什么不是越长越好 —— rerank 模型对超长文本的注意力会稀释，
        # 而且候选里有 10 条，每条都传满 4096 会让这一次请求变得很慢。
        # 我们的 index_text 前 1200 字符已经包含标题 + 主要数据点，够判别了。
        "documents": [d[:RERANK_MAX_DOC_CHARS] for d in documents],
        "top_n": top_n,
        "return_documents": False,                  # 不回传原文，省流量；我们本地有
        "return_raw_scores": RERANK_RETURN_RAW,     # 见上面那段实测对比，必须是 True
    }

    try:
        resp = requests.post(
            RERANK_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()                     # 4xx / 5xx 时抛 HTTPError，被下面接住
        data = resp.json()
    except Exception:
        # 这里**故意**吞掉所有异常（网络、鉴权、限流、JSON 格式变了……）。
        # 理由见函数文档末尾的"优雅降级"。
        # 但注意：吞掉不等于不告诉你 —— CLI 里 --no-rerank 和输出里的
        # "重排: 未启用/失败" 会让你一眼看出这一跳没生效。
        return None

    results = data.get("results") or []
    pairs: list[tuple[int, float]] = []
    for r in results:
        try:
            pairs.append((int(r["index"]), float(r["relevance_score"])))
        except (KeyError, TypeError, ValueError):
            continue                                # 响应结构变了就跳过这一条，别整个崩掉

    if not pairs:
        return None
    pairs.sort(key=lambda x: -x[1])
    return pairs


def normalize_scores(pairs: list[tuple[int, float]]) -> list[tuple[int, float]]:
    r"""把重排分做 min-max 归一化，压到 0~1 区间。

    为什么要归一化 —— 打开 return_raw_scores 之后，分数是模型直接吐的 logits，
    范围随问题而变（这次实测是 12.4~24.3，换个问题可能是 -3~8）。不归一化会有两个麻烦：

        ① 没法跨问题比较"第 3 名和第 4 名差多少"，也就没法判断
           RERANK_TOP_N=3 这个截断点定得是紧是松。

        ② 想给某类块打折（比如 FIGURE_SCORE_PENALTY）时，直接乘系数
           对负数是**反效果** —— (-10) × 0.5 = -5，分数反而变高了，
           惩罚变成了奖励。这是个很容易埋进去、且极难发现的 bug。

    归一化之后：最高的变 1、最低的变 0，折扣系数的语义变得非常直白
    （0.5 就是打五折），而且对负数同样成立。

    边界情况：所有分数完全相同时（只有 1 条候选，或模型给了一模一样的分），
    hi == lo，除以 0 会炸 —— 这时统一给 1.0，让后续逻辑照常工作。
    """
    if not pairs:
        return []

    vals = [s for _, s in pairs]
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return [(i, 1.0) for i, _ in pairs]

    return [(i, (s - lo) / (hi - lo)) for i, s in pairs]


# ==================================================================
# 六、主角：混合检索器
# ==================================================================

class HybridRetriever:
    """一次初始化，多次检索。

    内部持有三样东西（都是"一次性加载、反复使用"的重资产）：
        self.chunks    全部子块（从 docs.jsonl 读来）
        self.bm25      BM25 索引（启动时对全部子块 tokenize 一遍并建倒排表）
        self.vectorstore  FAISS 向量库（可选 —— 没有它就只有关键词路）

    不要在每个请求里 new 这个类 —— 建 BM25 索引要遍历所有块分词，
    每请求一次都会重跑一遍。用文件末尾的 get_retriever()。
    """

    def __init__(self,
                 store_dir: Path = STORE_DIR,
                 enable_rerank: bool = RERANK_ENABLED,
                 expand_parent: bool = EXPAND_PARENT) -> None:
        self.store_dir = Path(store_dir)
        self.enable_rerank = enable_rerank
        self.expand_parent = expand_parent

        # ---- 读子块 ----
        self.chunks: list[Chunk] = load_chunks(self.store_dir)
        if not self.chunks:
            raise ValueError(f"{self.store_dir}/docs.jsonl 里一块都没有，请先跑 indexer")

        # id -> 下标。dense 路拿回来的是 Document（带 metadata.id），
        # 要靠这张表把它翻译回本地的 chunk 下标，才能和 BM25 路合并。
        self.by_id: dict[str, int] = {c.id: c.idx for c in self.chunks}

        # ---- 建 BM25 索引 ----
        # 注意用的是 strip_index_header 之后的 index_text ——
        # 把每个块都重复出现的 "[文件名 第N页 · 正文]" 标签剥掉，
        # 否则文件名会污染 IDF（详见 strip_index_header 的说明）。
        corpus = [tokenize(strip_index_header(c.index_text)) for c in self.chunks]
        self.bm25 = BM25Index(corpus, k1=BM25_K1, b=BM25_B)

        # ---- 读父块 ----
        self.parents: dict[str, dict] = load_parents(self.store_dir)

        # ---- 加载向量库（懒加载 + 容错）----
        # 放在 try 里、延迟 import，有两个原因：
        #   ① 只有 BM25 也要能跑（比如还没花钱建向量库时），
        #      不能让一个缺失的可选依赖把整个检索层拖死
        #   ② langchain_community 里的 FAISS 包装在不同版本间偶尔会动，
        #      万一 import 失败，我们至少降级成"纯 BM25 检索"，而不是全崩
        self.vectorstore = None
        self._vectorstore_error: str | None = None

        faiss_path = self.store_dir / "index.faiss"
        if not faiss_path.exists():
            self._vectorstore_error = "没有 index.faiss（向量库还没建）"
        else:
            try:
                from langchain_community.vectorstores import FAISS

                from backend.app.retrieval.embeddings import get_embeddings
                vs = FAISS.load_local(
                    str(self.store_dir),
                    get_embeddings(),
                    # FAISS 本地库靠 pickle 反序列化，官方默认禁止（怕加载到恶意文件）。
                    # 这里是我们自己生成的库，所以显式打开。
                    allow_dangerous_deserialization=True,
                )

                # ---- 一致性自检（这是本项目里最容易踩、且最不报错的一个坑）----
                #
                #   向量库里的向量个数，必须和 docs.jsonl 里的块数**一模一样**。
                #
                #   为什么常常对不上：
                #     改了切块规则（比如这次加了父块、改了中文长度），
                #     重跑了 chunking，但没有重跑 indexer。
                #     于是 docs.jsonl 是新的（104 块），index.faiss 还是旧的（1687 块）。
                #
                #   不对上会怎样：
                #     FAISS 照样能查、照样返回 10 条结果，但那些结果来自**上一版语料**，
                #     它们的 id 在新的 by_id 表里找不到 —— 语义路会被静默清空。
                #     如果不去查，你只会看到"混合检索效果怎么变差了"，
                #     根本想不到是库版本错配。所以这里主动拦下来，并说清原因。
                n_vec = vs.index.ntotal
                if n_vec != len(self.chunks):
                    self._vectorstore_error = (
                        f"向量库与语料对不上（index.faiss {n_vec} 个向量 vs "
                        f"docs.jsonl {len(self.chunks)} 块）—— 大概率是改过切块后"
                        f"没重建向量库。语义路已停用，请重跑："
                        f"python -m backend.app.ingestion.indexer"
                    )
                else:
                    self.vectorstore = vs
            except Exception as e:          # noqa: BLE001 —— 就是要兜住一切，见上面注释
                self._vectorstore_error = f"{type(e).__name__}: {e}"

    # ---------------------------------------------------------- ① 两路召回
    def _recall_dense(self, question: str, n: int, source: str | None) -> list[tuple[int, float]]:
        """「语义路」召回：把问题向量化，去 FAISS 找最近的 n 块。

        返回 [(chunk 下标, L2 距离)]，**已按相关度从高到低排好**。
        注意方向：FAISS 给的是 L2 距离，**越小越相似**，而 FAISS 本身就是
        按距离升序返回的，所以它的原顺序就是我们要的排名顺序 —— 不要再去 sort。

        为什么要连分数一起返回，不只返回下标：
            CLI 诊断要靠它显示"向量路觉得这一块有多近"。
            如果只给排名不给分数，你就看不出第 1 名和第 10 名到底是
            "差一点点"还是"差了十万八千里"，也就没法判断召回数该取 10 还是 20。

        为什么要自己从 Document 翻译回下标：
            FAISS 返回的是 Document 对象，双塔检索出来的块要和 BM25 的结果合并，
            必须有一个统一的身份标识。metadata 里的 id 就是它。
            顺便还起了**去重**作用：万一 FAISS 返回了两条 id 相同的块
            （理论上不该发生，但数据脏的时候会发生），这里只认第一条。
        """
        if self.vectorstore is None:
            return []           # 没有向量库 -> 这条路静默空转，不报错

        if source:
            hits = self.vectorstore.similarity_search_with_score(
                question, k=n, filter={"source": source})
        else:
            hits = self.vectorstore.similarity_search_with_score(question, k=n)

        out: list[tuple[int, float]] = []
        seen: set[int] = set()
        for doc, dist in hits:
            idx = self.by_id.get(doc.metadata.get("id", ""))
            if idx is not None and idx not in seen:
                seen.add(idx)
                out.append((idx, float(dist)))
        return out

    def _recall_bm25(self, question: str, n: int, source: str | None) -> list[tuple[int, float]]:
        """「关键词路」召回：BM25 打分，取前 n 块。返回 [(chunk 下标, BM25 分)]。

        source 过滤放在**打分之后**而不是之前，并且要多召回一些再筛
        （看下面 top_n 传的是 n*4）：如果先按手册筛掉一大半文档再打分，
        很可能筛完剩不到 n 条。多召回几倍再过滤，才凑得齐 n 条。
        """
        toks = tokenize(strip_index_header(question))
        if not toks:
            return []

        pairs = self.bm25.top_n(toks, n * 4 if source else n)

        out: list[tuple[int, float]] = []
        for doc_i, score in pairs:
            if source and self.chunks[doc_i].source != source:
                continue
            out.append((doc_i, score))
            if len(out) >= n:
                break
        return out

    # ---------------------------------------------------------- ③ 重排用的文字
    def _rerank_text(self, c: Chunk) -> str:
        """决定拿哪份文字送去重排。

        config.RERANK_SOURCE = "index_text"（默认）时用检索优化过的自描述句：

            表格块  "表格标题: 表1-1 CH32F103x 产品资源分配
                     CH32F103 C6T6 · 芯片引脚数 = 48
                     CH32F103 C6T6 · 闪存（字节） = 32K"

        而不是原始 markdown 表格：

            "| 产品型号 / 资源差异 | CH32F103 C6T6 | CH32F103 C8T6 |
             | 芯片引脚数 | 48 | 48 |"

        理由：自描述句的每个数值都绑着型号和指标名，rerank 模型一眼就能
        看出"这条和'C6T6 引脚数'的问题直接对上"。而 markdown 表格要靠
        模型自己在脑子里对齐行列，多一层推理就多一层出错的机会。
        """
        raw = c.index_text if RERANK_SOURCE == "index_text" else c.content
        return strip_index_header(raw).strip() or c.content

    # ---------------------------------------------------------- ④ 父块放大 + 打包
    def _pack(self,
              question: str,
              picked: list[tuple[int, float]],
              fused: dict[int, float],
              dense_ids: list[int],
              bm25_ids: list[int],
              rerank_used: bool) -> list[Document]:
        """把最终选中的块变成 Document 列表（含父块放大）。

        流程：
            对每个选中的子块 -> 查它的 parent_id -> 从 parents.json 取回父块原文
            父块之间去重（两个碎片同属一节时，那一节只送一次）

        为什么要去重：
            Top-3 里的两块很可能来自同一节（比如都出自"3.2 时钟系统"）。
            不去重就会把同一节内容送两遍 —— 白花 token，还可能让模型
            误以为"这段内容出现了两次，应该很重要"。
        """
        docs: list[Document] = []
        seen_parent: set[str] = set()

        for idx, score in picked:
            c = self.chunks[idx]

            # ---- 决定送什么文字：有父块就送父块，没有就送子块 ----
            parent = None
            if self.expand_parent and c.parent_id:
                parent = self.parents.get(c.parent_id)

            if parent:
                if c.parent_id in seen_parent:
                    # 这一节已经送过了 —— 不再重复送，
                    # 但要把它记到那个 Document 的 hit_ids 里（见下面 else 分支后的补充逻辑）
                    for d in docs:
                        if d.metadata.get("parent_id") == c.parent_id:
                            d.metadata["hit_ids"].append(c.id)
                            break
                    continue
                seen_parent.add(c.parent_id)
                text = (parent.get("content") or "").strip()
                page_start = parent.get("page_start", c.page_start)
                page_end = parent.get("page_end", c.page_end)
                pack_id = c.parent_id
                pack_type = f"parent:{c.type}"
            else:
                text = c.content.strip()
                page_start, page_end = c.page_start, c.page_end
                pack_id = c.id
                pack_type = c.type

            if not text:
                continue

            # ---- 记录这一块是从哪条路来的（解释"为什么它被选中"）----
            via: list[str] = []
            if idx in dense_ids:
                via.append("dense")
            if idx in bm25_ids:
                via.append("bm25")

            docs.append(Document(
                page_content=text,
                metadata={
                    "id": pack_id,
                    "parent_id": c.parent_id,
                    "hit_ids": [c.id],            # 代表这一包里命中的子块（可能被追加）
                    "source": c.source,
                    "type": pack_type,
                    "title": c.title or (parent.get("title", "") if parent else ""),
                    "page_start": page_start,
                    "page_end": page_end,
                    "score": round(score, 6),     # 最终用于排序的那个分（重排分或融合分）
                    "rrf_score": round(fused.get(idx, 0.0), 6),
                    "via": "+".join(via) or "?",
                    "rerank": rerank_used,
                },
            ))

        return docs

    # ---------------------------------------------------------- 主入口
    def retrieve(self,
                 question: str,
                 source: str | None = None,
                 recall_dense: int = RECALL_DENSE,
                 recall_bm25: int = RECALL_BM25,
                 fused_top: int = FUSED_TOP,
                 top_n: int = RERANK_TOP_N) -> dict:
        """走完整链路，返回**诊断字典**（不是只返回结果）。

        为什么返回一个"什么都往里塞"的字典，而不是直接返回 list[Document]：
            调检索是个反复调参的活（RRF_K 该取多少、要不要开重排、
            重排该拿几块……）。如果每次调参都只能看到"最后选出来的 3 块"，
            你没法判断是召回阶段就没捞到，还是融合阶段把它挤掉了，
            还是重排阶段把它误杀了。

            这个字典把**每一跳的中间结果**都摊开，
            hybrid.py 的 CLI 会把它打印成表格，一眼看出问题出在哪一跳。

        字典结构：
            question      问题原文
            dense         向量路召回的**下标**列表（按相关度排序，给 RRF 用）
            dense_scored  向量路召回的 [(下标, L2 距离)]（给人看，距离越小越相似）
            bm25          BM25 路召回的**下标**列表（按分排序，给 RRF 用）
            bm25_scored   BM25 路召回的 [(下标, BM25 分)]（给人看）
            fused         RRF 融合后的 [(下标, 融合分)]（已排序、已截断到 fused_top）
            rerank_raw    重排接口返回的原始分 [(下标, raw logits)]（未启用/失败时 None）
            rerank        重排后**实际用于排序**的 [(下标, 归一化打折后的分)]（同上）
            picked        最终选中的 [(下标, 决定排序用的分)]
            docs          最终打包好的 Document 列表（给 rag_service 用）
            timings       各阶段耗时（秒）
            notes         人话说明（哪条路关了、重排为什么没用上等）

        为什么 dense / bm25 和 dense_scored / bm25_scored 要各存一份：
            RRF 只需要"顺序"（所以传纯下标列表最干净）；
            而人要看的是"分数"，尤其想知道**第 1 名和第 10 名差多少** ——
            那个差值才决定了召回数该调大还是调小。
            两个用途混在一个结构里，两种人都别扭，所以分开存。
        """
        timings: dict[str, float] = {}
        notes: list[str] = []

        # ---- ① 两路召回 ----
        # 注意：两路的排序方向是**相反**的（dense 是距离越小越好，BM25 是分越大越好），
        # 但两边都已经按"最相关在前"排好了，所以 RRF 只管排名、不管方向 —— 
        # 这正是 RRF 最省心的地方。
        t = time.time()
        dense_scored = self._recall_dense(question, recall_dense, source)
        timings["dense"] = time.time() - t
        dense_ids = [i for i, _ in dense_scored]

        t = time.time()
        bm25_scored = self._recall_bm25(question, recall_bm25, source)
        timings["bm25"] = time.time() - t
        bm25_ids = [i for i, _ in bm25_scored]

        if self.vectorstore is None:
            notes.append(f"语义路未启用（{self._vectorstore_error}），本次只有关键词路")
        if source:
            notes.append(f"已限定手册：{source}")

        # ---- ② RRF 融合 ----
        # 排完序再截断到 fused_top（=10）。
        # 排序键 (-分数, 下标)：分数降序；分数打平时按下标升序 ——
        # 同样是为了**结果稳定可复现**，不然两个分数相同的块谁在前谁在后是随机的。
        fused_map = rrf_fuse([dense_ids, bm25_ids], k=RRF_K)
        fused = sorted(fused_map.items(), key=lambda kv: (-kv[1], kv[0]))[:fused_top]

        # ---- ③ 重排 ----
        rerank_pairs: list[tuple[int, float]] | None = None
        rerank_raw: list[tuple[int, float]] | None = None
        rerank_used = False

        if not self.enable_rerank:
            notes.append("重排未启用（--no-rerank）")
        elif not fused:
            notes.append("候选池为空，跳过重排")
        else:
            t = time.time()
            cand_texts = [self._rerank_text(self.chunks[i]) for i, _ in fused]
            # top_n 传 len(fused)：把候选池里所有的分数都要回来。
            # 反正池子就 10 条，多要几条不额外花钱，
            # 反而能给诊断输出提供完整的"落选者分数"，方便看"第 4 名和
            # 第 3 名差多少"——这个差值能告诉你 RERANK_TOP_N 取 3 是不是太紧。
            pairs = zhipu_rerank(question, cand_texts, top_n=len(fused))
            timings["rerank"] = time.time() - t

            if pairs:
                # 关键翻译：rerank 返回的 index 是"在候选池里的位置"（0 开始），
                # 必须映射回真正的 chunk 下标，否则后面取到的就是别的块。
                mapped = [
                    (fused[pos][0], score)
                    for pos, score in pairs
                    if 0 <= pos < len(fused)
                ]
                rerank_raw = mapped          # 原始 raw logits，只给人看诊断

                # 两步后处理，顺序不能反：
                #   ① 归一化到 0~1   —— 否则下一步乘折扣对负数会变成"奖励"
                #   ② 图形指针块打五折 —— 让"指路牌"不去挤占"内容"的位置
                # 两者的理由分别见 normalize_scores 和 config.FIGURE_SCORE_PENALTY。
                normed = normalize_scores(mapped)
                rerank_pairs = [
                    (idx,
                     score * (FIGURE_SCORE_PENALTY if self.chunks[idx].type == "figure" else 1.0))
                    for idx, score in normed
                ]
                rerank_pairs.sort(key=lambda kv: (-kv[1], kv[0]))
                rerank_used = True
            else:
                notes.append("重排接口未返回结果（网络/额度/未配置 Key），已回退用融合分排序")

        # ---- 决定最终排序 ----
        if rerank_used and rerank_pairs:
            order = rerank_pairs
        else:
            order = [(i, s) for i, s in fused]      # 回退：融合分的顺序

        picked = order[:top_n]

        # ---- ④ 打包（含父块放大）----
        docs = self._pack(question, picked, fused_map, dense_ids, bm25_ids, rerank_used)

        if self.expand_parent and not self.parents:
            notes.append("没有 parents.json，本次未做父块放大")

        return {
            "question": question,
            "source": source,
            "dense": dense_ids,
            "dense_scored": dense_scored,
            "bm25": bm25_ids,
            "bm25_scored": bm25_scored,
            "fused": fused,
            "rerank_raw": rerank_raw,
            "rerank": rerank_pairs,
            "picked": picked,
            "docs": docs,
            "timings": timings,
            "notes": notes,
        }

    def search(self,
               question: str,
               source: str | None = None,
               top_n: int = RERANK_TOP_N,
               **kwargs) -> list[Document]:
        """给 rag_service 用的简化入口：只要最终结果，不要诊断信息。"""
        return self.retrieve(question, source=source, top_n=top_n, **kwargs)["docs"]


# ==================================================================
# 七、单例
# ==================================================================
_retriever: HybridRetriever | None = None


def get_retriever() -> HybridRetriever:
    """返回进程内唯一的检索器实例。

    和 services/rag_service.py 的 get_engine() 是同一个套路：
    第一次调用时真正建索引（几秒），之后每次调用直接返回同一份。
    main.py 在服务启动时调一次，等于把 BM25 索引提前建好放进内存。
    """
    global _retriever
    if _retriever is None:
        _retriever = HybridRetriever()
    return _retriever


def reset_retriever() -> None:
    """把单例丢掉，让下次调用重新从磁盘加载。

    【2026-10-03 新增，配合网页端"入库"功能】

    为什么需要它：
        上面那个单例是"启动时读一次磁盘、之后一直吃内存"的设计 ——
        这是它快的原因，也是它唯一的代价：**磁盘变了它不知道**。

        网页端建库完成后，新的向量和语料写进了 vectorstore/，
        但内存里这个实例还是旧的。不重置的后果是那个最让人困惑的现象：
        **后台明明显示"已入库"，提问却怎么都搜不到新手册。**
        排查的人会去怀疑向量库、怀疑检索参数、怀疑 embedding 模型，
        唯独想不到"内存里那份没换"。

    为什么只置空、不在这里立刻重建：
        重建要几秒（读语料 + 分词建 BM25 + 加载 FAISS）。
        建库线程里同步重建的话，用户点完按钮要白等几秒；
        而且紧接着的那次提问本来就要加载它。
        置空 = 把这几秒挪到真正需要它的那一刻（下一次提问）。

    为什么做成模块内的正规函数，而不是让调用方直接改 _retriever：
        `_retriever` 是模块私有变量。外面 `import hybrid; hybrid._retriever = None`
        虽然也能生效，但那是**绕过封装** —— 以后这里加了别的缓存
        （比如父块表也加了缓存），外面那句赋值就只清了一半，
        而且报错都报不出来。把重置逻辑留在本模块内，才是最不容易漏的做法。
    """
    global _retriever
    _retriever = None


# ==================================================================
# 八、命令行自测：把每一跳都打印成人能看的表格
# ==================================================================

def _fmt_chunks(chunks: list[Chunk], idxs, scores=None, limit: int = 12) -> str:
    """把一串块下标格式化成对齐的多行文本，供 CLI 打印。"""
    lines = []
    for rank, item in enumerate(idxs[:limit], 1):
        if isinstance(item, tuple):
            idx, score = item
        else:
            idx, score = item, (scores or {}).get(item, 0.0)
        c = chunks[idx]
        head = strip_index_header(c.index_text).replace("\n", " ")[:58]
        lines.append(
            f"    {rank:>2}. [{score:>9.6f}] {c.source[:26]:<26} "
            f"p{c.page_start:<3} {c.type:<6} {head}"
        )
    return "\n".join(lines) if lines else "    （空）"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="混合检索自测：打印两路召回 -> RRF 融合 -> 重排 -> 父块放大的每一跳")
    ap.add_argument("question", nargs="*", help="要检索的问题（不传则用一个默认问题）")
    ap.add_argument("--source", default=None, help="只在这份手册里搜，如 CH32F103_Datasheet_CN.pdf")
    ap.add_argument("--no-rerank", action="store_true", help="关掉重排，只看 RRF 融合的结果")
    ap.add_argument("--no-parent", action="store_true", help="关掉父块放大，只送命中的碎片")
    ap.add_argument("--top", type=int, default=RERANK_TOP_N, help=f"最终取几块（默认 {RERANK_TOP_N}）")
    ap.add_argument("--store", default=str(STORE_DIR), help="向量库目录")
    args = ap.parse_args()

    question = " ".join(args.question) or "CH32F103C6T6 的引脚数和闪存容量是多少"
    store = Path(args.store)

    print("=" * 78)
    print("混合检索自测")
    print("=" * 78)
    print(f"  问题   : {question}")
    print(f"  库目录 : {store}")
    print(f"  开关   : 重排={'开' if not args.no_rerank else '关'}"
          f"  父块放大={'开' if not args.no_parent else '关'}")
    print()

    try:
        r = HybridRetriever(store_dir=store,
                            enable_rerank=not args.no_rerank,
                            expand_parent=not args.no_parent)
    except FileNotFoundError as e:
        print(f"[错误] {e}")
        sys.exit(1)

    print(f"已加载 {len(r.chunks)} 个子块、{len(r.parents)} 个父块，"
          f"向量库 {'已就绪' if r.vectorstore is not None else '未启用'}")

    # 建索引的耗时单独测一次，让用户知道"启动成本"花在哪
    t0 = time.time()
    BM25Index([tokenize(strip_index_header(c.index_text)) for c in r.chunks])
    print(f"BM25 建索引耗时（参考值）: {time.time() - t0:.2f} 秒")
    print()

    res = r.retrieve(question, source=args.source, top_n=args.top)

    print("-" * 78)
    print(f"① 语义路（向量）召回 {len(res['dense'])} 条   "
          f"耗时 {res['timings'].get('dense', 0):.3f}s   （L2 距离，越小越相似）")
    print("-" * 78)
    print(_fmt_chunks(r.chunks, res["dense_scored"]))

    print()
    print("-" * 78)
    print(f"① 关键词路（BM25）召回 {len(res['bm25'])} 条   "
          f"耗时 {res['timings'].get('bm25', 0):.3f}s   （分数，越大越相关）")
    print("-" * 78)
    print(_fmt_chunks(r.chunks, res["bm25_scored"]))

    print()
    print("-" * 78)
    print(f"② RRF 融合后候选池（取前 {FUSED_TOP} 条）")
    print("-" * 78)
    print(_fmt_chunks(r.chunks, res["fused"]))

    print()
    print("-" * 78)
    if res["rerank"] is None:
        print(f"③ 重排：未生效   {'; '.join(res['notes'])}")
        print("-" * 78)
    else:
        print(f"③ 重排后（智谱 rerank）  耗时 {res['timings'].get('rerank', 0):.3f}s")
        print(f"   原始分 -> min-max 归一化 -> 图形指针块再打 {FIGURE_SCORE_PENALTY} 折")
        print("-" * 78)
        raw_map = dict(res["rerank_raw"] or [])
        for rank, (idx, score) in enumerate(res["rerank"], 1):
            c = r.chunks[idx]
            flag = f"   ← 图形指针块，raw {raw_map.get(idx, 0):.2f} 已被折扣" if c.type == "figure" else ""
            print(f"    {rank:>2}. raw={raw_map.get(idx, 0):>9.4f} -> 终分={score:.4f}  "
                  f"p{c.page_start:<3} {c.type:<6} "
                  f"{strip_index_header(c.index_text).replace(chr(10), ' ')[:42]}{flag}")

    print()
    print("-" * 78)
    print(f"④ 最终选中 {len(res['picked'])} 块  ->  父块放大后打包 {len(res['docs'])} 个 Document")
    print("-" * 78)
    for d in res["docs"]:
        m = d.metadata
        print(f"    id={m['id']}  type={m['type']}  来自={m['via']}  "
              f"分={m['score']}  p{m['page_start']}-{m['page_end']}")
        print(f"      命中碎片: {m['hit_ids']}")
        print(f"      标题: {m['title'][:70]}")
        print(f"      正文前 220 字: {d.page_content[:220].replace(chr(10), ' ')}")
        print()

    if res["notes"]:
        print("提示:")
        for n in res["notes"]:
            print(f"    - {n}")
    print("=" * 78)


if __name__ == "__main__":
    main()
