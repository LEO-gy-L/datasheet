import { CommentOutlined } from "@ant-design/icons";
import { App, Form, Input, Modal, Select } from "antd";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { ask } from "@/api/chat.js";
import { createFeedback, FEEDBACK_CATEGORIES } from "@/api/feedback.js";
import DocPicker from "@/components/DocPicker.jsx";
import { useAuth } from "@/context/AuthContext.jsx";
import {
  animateIntro,
  animateMeta,
  animateRowIn,
  animateTyping,
} from "@/utils/chatAnimation.js";
import { safeValidate } from "@/utils/form.js";
// markdown -> 安全 HTML。抽到 utils 里是因为历史问答页也要渲染同一批答案，
// 两处各写一份的话，将来"忘了在其中一处加 DOMPurify"就是个真的 XSS 漏洞。
import { toHtml } from "@/utils/markdown.js";

import "@/assets/css/assistant.css";

/** 首屏的建议问题：点一下就直接发出去 */
const QUICK_ASKS = [
  "CH32F103C6T6 的引脚数是多少？",
  "闪存和 SRAM 分别是多大？",
  "支持哪些通信接口？",
];

/**
 * 用户 · datasheet 助理
 * =====================
 * 这个页面有两层设计：
 *
 * ① 观感 —— 布局与动效沿用旧版整页界面，配色换成「极简高级灰」。
 *    无彩色、近黑强调、细边框、小圆角。动效仍由 anime.js 驱动：
 *      入场时间轴 · 每条消息浮入 · 三个点跳动 · 来源标签错落出现
 *    样式在 assets/css/assistant.css，动效在 utils/chatAnimation.js。
 *
 *    旧版页面内那一行"品牌 + 后端状态"已删除：外层顶栏本来就有同款信息，
 *    页面里再来一行属于重复。后端状态看顶栏那个小圆点即可。
 *
 * ② 功能 —— 唯一一个**真连后端**的页面：/api/ask 直接打，
 *    所以问答是真答（带出处页码），不是 mock。
 *    每条 AI 回答下面挂一个「反馈」按钮，点开弹窗自动带上
 *    "这一轮的提问 + 系统的回答"，用户只选分类写一句就行。
 */
export default function Assistant() {
  const { user } = useAuth();
  const { message } = App.useApp();

  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);

  /* 检索范围："" = 全部手册；否则是某份手册的文件名。
     这个值会被原样传给后端的 /api/ask（见下面 send 里的 ask(q, { source })). */
  const [scope, setScope] = useState("");

  // 正在被反馈的那条 AI 消息
  const [fbTarget, setFbTarget] = useState(null);
  const [fbForm] = Form.useForm();
  const [fbSaving, setFbSaving] = useState(false);

  const rootRef = useRef(null);   // 整页根节点：动画的范围限定在它里面
  const listRef = useRef(null);   // 消息滚动区
  const typingRef = useRef(null); // "正在思考"那三个点
  const seq = useRef(0);          // 消息 id 自增源，比时间戳可靠（同一毫秒加两条也不会撞）

  /* ---------- 入场动画：只在挂载时跑一次 ---------- */
  // 用 useLayoutEffect 而不是 useEffect：
  //   它会在浏览器绘制**之前**同步执行，动画从第一帧就生效。
  //   换成 useEffect 的话，元素会先以"最终状态"闪一下再跳回起点，很难看。
  useLayoutEffect(() => {
    animateIntro(rootRef.current);
  }, []);

  /* ---------- 新消息进场动画 ---------- */
  useLayoutEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const rows = root.querySelectorAll(".row");
    if (!rows.length) return;

    const last = rows[rows.length - 1]; // 只管新加的这一行，老消息不重复播
    animateRowIn(last);

    // 如果这行是 AI 的回答，来源标签 / 耗时再错落浮入一次
    if (last.classList.contains("ai")) animateMeta(last);
  }, [messages]);

  /* ---------- "正在思考"三个点跳起来 ---------- */
  useEffect(() => {
    if (sending && typingRef.current) animateTyping(typingRef.current);
  }, [sending]);

  /* ---------- 新消息自动滚到底 ---------- */
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, sending]);

  /* ---------- 提问 ---------- */
  async function send(text) {
    const q = (text ?? input).trim();
    if (!q || sending) return;

    setInput("");
    setMessages((prev) => [...prev, { id: ++seq.current, who: "user", text: q }]);
    setSending(true);

    try {
      // source 传 undefined 时 JSON.stringify 会**整个省略这个键**，
      // 后端 pydantic 收到的是默认值 None = 在全部手册里检索。
      // 这就是为什么这里写 `scope || undefined` 而不是 `scope`：
      // 传空字符串 "" 的话后端会拿它去过滤 source == ""，一轮都命不中。
      const data = await ask(q, { source: scope || undefined });
      setMessages((prev) => [
        ...prev,
        {
          id: ++seq.current,
          who: "ai",
          text: data.answer ?? "",
          sources: data.sources ?? [],
          seconds: data.seconds,
          // 把这一轮的提问存进这条回答里：反馈弹窗要用
          question: q,
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: ++seq.current,
          who: "ai",
          text: `出错了：${err.message}`,
          sources: [],
          question: q,
          isError: true,
        },
      ]);
    } finally {
      setSending(false);
    }
  }

  /* ---------- 切换检索范围 ---------- */
  function changeScope(next) {
    setScope(next);

    // 换范围时清空当前对话 —— 理由见 DocPicker.jsx 文件头的说明：
    // 旧回答是在**旧范围**下得出的，留在屏幕上和新的混在一起，
    // 回头再看根本分不清哪句是哪个范围给的。
    //
    // 为什么要给一句提示而不是默默清掉：
    //   消息突然消失是很惊悚的体验，用户会以为"我是不是点错了什么"。
    //   说一句"已切换 + 对话已清空"，行为就可预期了。
    if (messages.length > 0) {
      setMessages([]);
      message.info(
        next ? `已限定只在《${next}》里检索，对话已清空` : "已切回全部手册，对话已清空"
      );
    } else {
      message.success(next ? `已限定只在《${next}》里检索` : "已切回全部手册");
    }
  }

  /* ---------- 反馈 ---------- */
  function openFeedback(msg) {
    setFbTarget(msg);
  }

  // 弹窗打开之后，再往表单里回填初始值。
  //
  // 为什么不在 openFeedback 里直接 setFieldsValue：
  //   Modal 开了 destroyOnHidden，关闭状态下里面的 <Form> 是**不存在**的。
  //   在"刚点开、Modal 还没渲染出来"的这一刻去 setFieldsValue，
  //   表单实例还没连上任何 Form 元素，antd 就会抛一句警告：
  //     "Instance created by `useForm` is not connected to any Form element"
  //   挪进 effect 里，执行时机自然就落在 Form 挂载之后了。
  useEffect(() => {
    if (fbTarget) {
      fbForm.setFieldsValue({ category: FEEDBACK_CATEGORIES[0], content: "" });
    }
  }, [fbTarget, fbForm]);

  async function submitFeedback() {
    // 内容为空时返回 null：antd 会在文本框下面画红字，这里直接收工
    const values = await safeValidate(fbForm);
    if (!values) return;
    setFbSaving(true);
    try {
      await createFeedback({
        username: user.username,
        category: values.category,
        content: values.content,
        question: fbTarget.question,
        answer: fbTarget.text,
      });
      setFbTarget(null);
      fbForm.resetFields();
      message.success("反馈已提交，管理员处理后在「问题反馈」页能看到回复");
    } catch (err) {
      message.error(err.message);
    } finally {
      setFbSaving(false);
    }
  }

  return (
    <div className="ds-assistant" ref={rootRef}>
      {/* 标题区（原 css/hero.css） */}
      <h1 className="ds-title">数据手册智能咨询</h1>
      <p className="sub">把芯片数据手册丢进来，用大白话提问，答案带出处。</p>

      <div className="badges">
        <span className="badge">LangChain</span>
        <span className="badge">FAISS 向量检索</span>
        <span className="badge">DeepSeek 生成</span>
        <span className="badge">FastAPI 后端</span>
      </div>

      {/* 聊天卡片（原 css/cards.css + lab.css） */}
      <div className="card">
        <div className="chat" ref={listRef}>
          {messages.length === 0 ? (
            <div className="hello">
              {/* 原来这里有个 👋 —— 灰阶体系里彩色 emoji 是唯一的高饱和元素，
                  很跳，去掉了。想要温度的话，界面的留白和语气已经够了。 */}
              <div className="hi">你好，我是 datasheet 助理</div>
              <p>问我关于数据手册的问题吧，答案会带出处页码。</p>
              <div className="chips">
                {QUICK_ASKS.map((q) => (
                  <div key={q} className="chip" onClick={() => send(q)}>
                    {q}
                  </div>
                ))}
              </div>
            </div>
          ) : (
            messages.map((msg) => (
              <div key={msg.id} className={`row ${msg.who}`}>
                <div className="avatar">{msg.who === "user" ? "我" : "AI"}</div>

                <div className="body">
                  {msg.who === "ai" ? (
                    msg.isError ? (
                      <div className="bubble error">{msg.text}</div>
                    ) : (
                      <div className="bubble md" dangerouslySetInnerHTML={toHtml(msg.text)} />
                    )
                  ) : (
                    <div className="bubble">{msg.text}</div>
                  )}

                  {msg.who === "ai" && (
                    <div className="msg-actions">
                      {msg.sources?.map((s, i) => (
                        <span key={i} className="src">
                          {s}
                        </span>
                      ))}

                      <span className="meta">
                        {typeof msg.seconds === "number" && <span>耗时 {msg.seconds}s</span>}
                        <button
                          type="button"
                          className="fb-btn"
                          onClick={() => openFeedback(msg)}
                        >
                          <CommentOutlined style={{ fontSize: 11 }} />
                          反馈
                        </button>
                      </span>
                    </div>
                  )}
                </div>
              </div>
            ))
          )}

          {/* 等待回答时：三个跳动的点 */}
          {sending && (
            <div className="row ai">
              <div className="avatar">AI</div>
              <div className="body">
                <div className="bubble" ref={typingRef}>
                  <div className="typing">
                    <i />
                    <i />
                    <i />
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* 检索范围选择器（"只在这份手册里提问"）。
            放在输入栏上方的**卡片内部**，因为它修饰的是"这一个问题"的范围，
            紧挨着输入框才有这个语义；放到页面顶栏就变成一个全局设置了。 */}
        <div className="scopebar">
          <DocPicker
            value={scope}
            onChange={changeScope}
            // 正在等待回答时禁用：这一轮请求已经带着旧的范围发出去了，
            // 中途换掉会让人以为"改的是这一轮"，其实不是。
            disabled={sending}
          />
        </div>

        {/* 输入栏（原 css/lab.css） */}
        <div className="inputbar">
          <input
            className="q"
            type="text"
            placeholder="输入关于数据手册的问题……"
            autoComplete="off"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") send();
            }}
          />
          <button
            type="button"
            className="send"
            title="发送"
            disabled={sending}
            onClick={() => send()}
          >
            {/* 向上箭头。用内联 SVG 而不是图标字体：不打字体请求，也没有加载闪烁 */}
            <svg
              width="19"
              height="19"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M12 19V5M5 12l7-7 7 7" />
            </svg>
          </button>
        </div>
      </div>

      <p className="tip">
        后端没反应？先在项目目录双击 <code>start_backend.bat</code> 启动服务
      </p>

      {/* 反馈弹窗：功能部分用 antd，观感不动 */}
      <Modal
        title="反馈这条回答"
        open={Boolean(fbTarget)}
        onCancel={() => setFbTarget(null)}
        onOk={submitFeedback}
        confirmLoading={fbSaving}
        okText="提交反馈"
        cancelText="取消"
        destroyOnHidden
      >
        <div
          style={{
            background: "var(--bg-subtle)",
            border: "1px solid var(--line)",
            padding: 10,
            borderRadius: 8,
            margin: "12px 0",
          }}
        >
          <div style={{ fontSize: 12, color: "var(--ink-faint)" }}>你问的</div>
          <p style={{ margin: "2px 0 8px", fontSize: 13 }}>{fbTarget?.question}</p>
          <div style={{ fontSize: 12, color: "var(--ink-faint)" }}>系统回答</div>
          <p style={{ margin: "2px 0 0", fontSize: 13, maxHeight: 90, overflow: "auto" }}>
            {fbTarget?.text}
          </p>
        </div>

        <Form form={fbForm} layout="vertical">
          <Form.Item name="category" label="问题分类" rules={[{ required: true }]}>
            <Select options={FEEDBACK_CATEGORIES.map((c) => ({ label: c, value: c }))} />
          </Form.Item>
          <Form.Item
            name="content"
            label="具体说明"
            rules={[{ required: true, message: "说说哪里不对" }]}
          >
            <Input.TextArea rows={4} placeholder="哪里不对？期望的答案是什么？" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
