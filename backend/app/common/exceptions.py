# -*- coding: utf-8 -*-
"""
自定义异常
==========
为什么不直接用 Exception / ValueError，而要多写几个类：

    因为**接口层需要按错误类型返回不同的 HTTP 状态码**。
    如果全用 ValueError，接口里就只能写 `except ValueError` 一把抓，
    想区分"用户输入错了"和"上游模型挂了"就只剩"去匹配异常信息里的字符串"这条路 ——
    改一个字就失灵。

    自定义类型让这件事变成一眼可读：

        EmptyQuestionError    -> 400  用户输入有问题，改了再来
        IndexNotFoundError    -> 500  服务端自己没准备好（向量库没建）
        ModelCallError        -> 503  上游大模型挂了/限流，过会儿重试可能就好

    另外，它们都继承同一个 RAGError，所以"捕获本项目全部业务错误"可以只写一句
    `except RAGError`。

⚠️ 命名约定：类名以 Error 结尾、继承 Exception。
   不要写成 XxxException —— 项目里统一一种叫法，grep 的时候不会漏。
"""
from __future__ import annotations


class RAGError(Exception):
    """本项目所有业务异常的基类。

    自己写 except 时优先捕获它，而不是裸的 Exception ——
    裸 Exception 会把 Ctrl+C、内存不足、语法错误之类也一起吞掉，调试会很难受。
    """


class EmptyQuestionError(RAGError):
    """问题为空，或者全是空白字符。"""


class IndexNotFoundError(RAGError):
    """向量库不存在：还没有建库（没跑 indexer），或者 vectorstore/ 被删了。"""


class ModelCallError(RAGError):
    """调用大模型失败：网络抖动、余额不足、被限流。

    单独一类的原因：这是**唯一值得重试**的错误。
    """
