# -*- coding: utf-8 -*-
"""
大模型客户端（DeepSeek）
========================
职责：把"怎么创建模型对象"收敛到一处。
      以后换供应商（智谱 / 通义 / OpenAI）或者改默认参数，只改这个文件。

为什么写成**工厂函数**而不是模块级全局变量：

    模块级创建（`model = ChatDeepSeek(...)` 直接写在文件顶层）：
        一 import 就执行，没法传参、没法延迟、没法在测试里替换。

    工厂函数（下面这样）：
        谁需要谁调用，还能传参覆盖默认值；测试时也能自己造一个便宜的模型。

⚠️ 这也是 scripts/test_llm.py 和本文件的区别：
    test_llm.py 是"验证密钥能不能调通"的一次性脚本，它在 import 时就发请求；
    本文件是生产代码里被 service 调用的客户端工厂。两者不要混。
"""
from __future__ import annotations

from langchain_deepseek import ChatDeepSeek

from backend.app.config import LLM_MODEL


def get_llm(model: str | None = None, temperature: float = 0.0) -> ChatDeepSeek:
    """创建 DeepSeek 对话模型。

    model       : 模型名。默认取 config.LLM_MODEL，需要临时换模型时传参即可。
    temperature : 0 = 每次回答尽量一致。

    temperature 为什么默认 0：
        问答场景要的是"稳定复现"，同样的资料应该给出同样的答案。
        temperature 越高越发散 —— 那是写文案时想要的，不是查数据手册时想要的。
    """
    return ChatDeepSeek(model=model or LLM_MODEL, temperature=temperature)
