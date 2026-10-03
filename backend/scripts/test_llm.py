# -*- coding: utf-8 -*-
"""
连通性自检：DeepSeek 密钥能不能调通
==================================
用途：换机器、改过密钥、或者怀疑"网络是不是不通"的时候先跑这个。
      它只发一次极短的请求（几厘钱），能立刻区分"密钥/网络问题"和"业务问题"。

运行方法（**必须在项目根目录**）：
    python -m backend.scripts.test_llm

为什么把它归到 scripts/ 而不是 app/generation/：
    它在**顶层就发请求**（import 即执行），是"跑一次看结果"的检查工具，
    不是被服务调用的生产代码。生产用的客户端工厂在
    backend/app/generation/llm.py 里。

本脚本故意用**生产同款客户端工厂**（get_llm），
所以你在这里调通，服务里就一定调得通 —— 不会出现"配置不一致"这种鬼问题。
"""
import sys
from pathlib import Path

# 入口脚本特有：把项目根加进 sys.path，这样才能 import 到 backend 包
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import os  # noqa: E402

from backend.app.config import ENV_FILE  # noqa: E402
from backend.app.generation.llm import get_llm  # noqa: E402

# ---------- 1. 先确认密钥真的被读到了 ----------
api_key = os.getenv("DEEPSEEK_API_KEY")
if not api_key or "在这里填" in api_key:
    raise SystemExit(
        f"[失败] 没读到 DEEPSEEK_API_KEY。\n"
        f"       请检查这个文件里有没有填好：{ENV_FILE}"
    )

# 只打印头尾各 4 位，中间打码。
# 为什么不直接打印完整密钥：终端历史、录屏、截图都可能把它泄露出去。
print(f"密钥已读到：{api_key[:4]}****{api_key[-4:]}（长度 {len(api_key)}）")
print(f"配置文件  ：{ENV_FILE}")

# ---------- 2. 用生产同款客户端发一次请求 ----------
model = get_llm()
response = model.invoke("用一句话介绍你自己")

print("=" * 50)
print("模型回复：", response.content)
print("=" * 50)

# ---------- 3. token 账单（DeepSeek 按 token 计费） ----------
usage = getattr(response, "usage_metadata", None)
if usage:
    print("本次 token 用量：", usage)
    print("（prompt=输入、completion=输出；计费按两者之和算）")
