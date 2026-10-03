# -*- coding: utf-8 -*-
"""
第 5 步（加分项）：给项目套一个网页界面（Streamlit）
====================================================
运行方法（在 datasheet 目录下）：
    python -m streamlit run backend/scripts/streamlit_app.py
浏览器会自动打开 http://localhost:8501，像聊天软件一样用。

面试演示就用这个，比命令行有说服力得多。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 项目根

import streamlit as st   # noqa: E402

from backend.app.services.rag_service import RAGEngine   # noqa: E402


# ---------- 页面标题 ----------
st.set_page_config(page_title="Datasheet 智能问答", page_icon="📄")
st.title("📄 Datasheet 智能问答系统")
st.caption("基于 LangChain + FAISS + DeepSeek 的 RAG 应用")


# ---------- 加载资源（cache_resource 保证刷新页面不重复加载） ----------
@st.cache_resource
def load_engine() -> RAGEngine:
    return RAGEngine()


try:
    engine = load_engine()
except IndexNotFoundError as e:
    st.error(str(e))
    st.stop()


# ---------- 聊天记录（存在 session_state 里，刷新不丢） ----------
if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])


# ---------- 处理新提问 ----------
question = st.chat_input("输入关于数据手册的问题……")
if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        with st.spinner("检索资料并生成回答中……"):
            try:
                res = engine.ask(question)
            except Exception as e:
                st.error(f"出错了：{e}")
                st.stop()

            sources = res["sources"]
            full_answer = (
                res["answer"]
                + "\n\n---\n📎 来源：" + "、".join(sources)
                + f"\n\n⏱ 耗时 {res['seconds']} 秒"
            )
            st.write(full_answer)
            st.session_state.messages.append(
                {"role": "assistant", "content": full_answer}
            )
