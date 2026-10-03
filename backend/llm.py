# -*- coding: utf-8 -*-
"""
验证 DeepSeek 能调通
================================
运行方法（在 datasheet-rag 目录下）：
    .venv\\Scripts\\python backend\\llm.py
"""
import os
from dotenv import load_dotenv          # 负责读取 .env 文件里的密钥
from langchain_deepseek import ChatDeepSeek
load_dotenv()
api_key = os.getenv("DEEPSEEK_API_KEY")
if not api_key or "在这里填" in api_key:
    raise SystemExit("请先在 .env 文件里填入你的 DEEPSEEK_API_KEY！")
model = ChatDeepSeek(model="deepseek-chat", temperature=0)
response = model.invoke("用一句话介绍你自己")
print("=" * 50)
print("模型回复：", response.content)
print("=" * 50)
# # 5. usage_metadata 是这次调用的 token 账单（上次给你讲过的计费）
# print("本次 token 用量：", response.usage_metadata)
