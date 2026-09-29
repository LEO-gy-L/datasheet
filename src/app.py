# -*- coding: utf-8 -*-
"""
第 5 步（加分项）：给项目套一个网页界面（Streamlit）
====================================================
运行方法（在 datasheet-rag 目录下）：
    .venv\\Scripts\\python -m streamlit run src\\app.py
浏览器会自动打开 http://localhost:8501，像聊天软件一样用。

面试演示就用这个，比命令行有说服力得多。
"""

from pathlib import Path
from dotenv import load_dotenv
import streamlit as st
from langchain_community.embeddings import ZhipuAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_deepseek import ChatDeepSeek

load_dotenv()
BASE_DIR = Path(__file__).resolve().parents[1]
STORE_DIR = BASE_DIR / "vectorstore"

# ---------- 页面标题 ----------
st.set_page_config(page_title="Datasheet 智能问答", page_icon="📄")
st.title("📄 Datasheet 智能问答系统")
st.caption("基于 LangChain + FAISS + DeepSeek 的 RAG 应用")

# ---------- 加载资源（用 cache 装饰器，只加载一次，刷新页面不重复加载） ----------
@st.cache_resource
def load_resources():
    embeddings = ZhipuAIEmbeddings(model="embedding-3")
    store = FAISS.load_local(
        str(STORE_DIR), embeddings, allow_dangerous_deserialization=True
    )
    llm = ChatDeepSeek(model="deepseek-chat", temperature=0)
    return store, llm

if not (STORE_DIR / "index.faiss").exists():
    st.error("没找到向量库，请先在命令行运行 step3_vectorstore.py 建库")
    st.stop()

vectorstore, model = load_resources()

# ---------- 聊天记录（存在 session_state 里，刷新不丢） ----------
if "messages" not in st.session_state:
    st.session_state.messages = []

# 把历史消息显示出来
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# ---------- 处理新提问 ----------
question = st.chat_input("输入关于数据手册的问题……")
if question:
    # 显示用户问题
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.write(question)

    # 检索 + 生成（和 step4 完全相同的逻辑）
    with st.chat_message("assistant"):
        with st.spinner("检索资料并生成回答中……"):
            related_chunks = vectorstore.similarity_search(question, k=4)
            context = "\n\n".join(c.page_content for c in related_chunks)
            prompt = f"""你是一个芯片数据手册问答助手。请只根据下面提供的资料回答问题。
如果资料里没有答案，就直接说"数据手册中没有提到"，不要自己编。

【资料】
{context}

【问题】
{question}

【回答】"""
            response = model.invoke(prompt)
            answer = response.content

            # 出处带上页码；用 list 保持顺序稳定（set 每次顺序都不同）
            sources: list[str] = []
            for c in related_chunks:
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
            full_answer = answer + "\n\n---\n📎 来源：" + "、".join(sources)

            st.write(full_answer)
            st.session_state.messages.append({"role": "assistant", "content": full_answer})
