# -*- coding: utf-8 -*-
"""
第 1 步：验证 DeepSeek 能调通
================================
运行方法（在 datasheet-rag 目录下）：
    .venv\\Scripts\\python src\\step1_llm.py

看到模型回复一句话 + 一行 token 用量，就说明 API Key 和网络都没问题。
"""

import os
from dotenv import load_dotenv          # 负责读取 .env 文件里的密钥
from langchain_deepseek import ChatDeepSeek

# 1. 读取 .env 文件，把里面的 DEEPSEEK_API_KEY 装进环境变量
load_dotenv()

# 2. 检查密钥有没有读到，没读到就提前报错，别等网络请求失败才懵
api_key = os.getenv("DEEPSEEK_API_KEY")
if not api_key or "在这里填" in api_key:
    raise SystemExit("请先在 .env 文件里填入你的 DEEPSEEK_API_KEY！")

# 3. 创建模型对象
#    model="deepseek-chat" 指定用哪个模型
#    temperature=0 表示输出尽量稳定（问答场景要准确，不要它发挥创意）
model = ChatDeepSeek(model="deepseek-chat", temperature=0)

# 4. invoke = 发一条消息，拿回完整回复
#    返回的是一个 AIMessage 对象，.content 取文字内容
response = model.invoke("用一句话介绍你自己")

print("=" * 50)
print("模型回复：", response.content)
print("=" * 50)

# 5. usage_metadata 是这次调用的 token 账单（上次给你讲过的计费）
print("本次 token 用量：", response.usage_metadata)
