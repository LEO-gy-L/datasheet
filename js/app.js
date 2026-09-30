/* app.js —— 主控制器：后端检测 + 问答接口 + 事件绑定 */
import { API , dot, statusText, input, sendBtn, hello } from "./config.js" ; 
import { animateMeta } from "./animation.js" ;
import { addBubble, addTyping } from "./chat.js" ;
/* —— 后端状态检测 —— */
async function checkBackend() {
  try {
    const r = await fetch(API + "/api/health", { cache: "no-store" });
    if (!r.ok) throw new Error();
    dot.className = "dot ok";
    statusText.textContent = "后端已连接";
  } catch (e) {
    dot.className = "dot bad";
    statusText.textContent = "后端未启动";
  }
}
checkBackend();
setInterval(checkBackend, 8000);

/* —— 提问 —— */
async function ask(question) {
  if (!question.trim()) return;
  if (hello) hello.remove();

  addBubble(question, "user");
  input.value = "";
  input.disabled = true;
  sendBtn.disabled = true;

  const typingRow = addTyping();

  try {
    const res = await fetch(API + "/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: question })
    });
    if (!res.ok) throw new Error("接口返回 " + res.status);
    const data = await res.json();

    typingRow.remove();

    const { row, bubble } = addBubble(data.answer, "ai");

    if (data.sources && data.sources.length) {
      const box = document.createElement("div");
      box.className = "sources";
      data.sources.forEach(s => {
        const tag = document.createElement("span");
        tag.className = "src";
        tag.textContent = "📎 " + s;
        box.appendChild(tag);
      });
      bubble.appendChild(box);
    }

    if (data.seconds !== undefined) {
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = "耗时 " + data.seconds + " 秒";
      bubble.appendChild(meta);
    }

    animateMeta(row);                    // 原来是直接写 anime(...)
  } catch (e) {
    typingRow.remove();
    addBubble("出错了：" + e.message + "\n请确认后端已启动（双击 start_backend.bat）。", "ai");
  } finally {
    input.disabled = false;
    sendBtn.disabled = false;
    input.focus();
  }
}

/* —— 事件绑定 —— */
sendBtn.addEventListener("click", () => ask(input.value));
input.addEventListener("keydown", e => { if (e.key === "Enter") ask(input.value); });
document.querySelectorAll(".chip").forEach(chip => {
  chip.addEventListener("click", () => ask(chip.textContent));
});