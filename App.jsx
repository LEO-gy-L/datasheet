const API = window.API_URL || "http://127.0.0.1:8000";
import { useState,useEffect } from "react";

export default function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");

    const [backend, setBackend] = useState("checking");

  useEffect(() => {
    async function check() {
      try {
        const r = await fetch(API + "/api/health", { cache: "no-store" });
        if (!r.ok) throw new Error();
        setBackend("ok");
      } catch (e) {
        setBackend("bad");
      }
    }
    check();
    const timer = setInterval(check, 8000);
    return () => clearInterval(timer);
  }, []);

  const dotClass = "dot " + (backend === "ok" ? "ok" : backend === "bad" ? "bad" : "");
  const statusWord = backend === "ok" ? "后端已连接" : backend === "bad" ? "后端未启动" : "检测后端中…";
  async function send(question) {
    const q = (question || input).trim();
    if (!q) return;

    setMessages(prev => [...prev, { text: q, who: "user" }]);
    setInput("");

    try {
      const res = await fetch(API + "/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      if (!res.ok) throw new Error("接口返回 " + res.status);
      const data = await res.json();
      setMessages(prev => [...prev, { text: data.answer, who: "ai" }]);
    } catch (e) {
      setMessages(prev => [...prev, { text: "出错了：" + e.message + "（请确认后端已启动）", who: "ai" }]);
    }
  }
  return (
    <div className="wrap">
      <div className="topbar">
        <div className="brand"><b>Datasheet RAG</b> · 芯片数据手册咨询</div>
        <div className="status">
           <span className={dotClass} id="dot"></span>
           <span id="statusText">{statusWord}</span>
        </div>
      </div>

      <h1 id="title">数据手册智能咨询</h1>
      <p className="sub">把芯片数据手册丢进来，用大白话提问，答案带出处。</p>

      <div className="badges">
        <span className="badge">LangChain</span>
        <span className="badge">FAISS 向量检索</span>
        <span className="badge">DeepSeek 生成</span>
        <span className="badge">FastAPI 后端</span>
      </div>

      <div className="card">
        <div className="chat" id="chat">
          {messages.length === 0 ? (
            <div className="hello" id="hello">
              <div className="hi">👋 你好，我是数据手册助手</div>
              <p>问我关于数据手册的问题吧</p>
              <div className="chips">
                <div className="chip" onClick={() => send("GPIO 最大输出电流是多少？")}>GPIO 最大输出电流是多少？</div>
                <div className="chip" onClick={() => send("待机功耗多少？")}>待机功耗多少？</div>
                <div className="chip" onClick={() => send("支持哪些通信接口？")}>支持哪些通信接口？</div>
              </div>
            </div>
          ) : (
            messages.map((msg, i) => (
              <div key={i} className={"row " + msg.who}>
                <div className="avatar">{msg.who === "user" ? "我" : "AI"}</div>
                <div className="bubble">{msg.text}</div>
              </div>
            ))
          )}
        </div>

        <div className="inputbar">
          <input
            id="q"
            type="text"
            placeholder="输入关于数据手册的问题……"
            autoComplete="off"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") send(); }}
          />
          <button id="send" title="发送" onClick={() => send()}>
            <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 19V5M5 12l7-7 7 7" />
            </svg>
          </button>
        </div>
      </div>

      <p className="tip">后端没反应？先在项目目录双击 <code>start_backend.bat</code> 启动服务</p>
    </div>
  );
}