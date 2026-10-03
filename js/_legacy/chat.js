import { chat } from "./config.js" ; 
import { animateRowIn, animateTyping } from "./animation.js" ; // 拿两个动画函数 
const marked = window . marked ;
/* chat.js —— 聊天气泡渲染 */
function makeRow(who) {
  const row = document.createElement("div");
  row.className = "row " + who;

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = who === "user" ? "我" : "AI";
  row.appendChild(avatar);

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  row.appendChild(bubble);

  chat.appendChild(row);          // chat 来自 config.js
  return { row, bubble };
}

export function addBubble(text, who) {
  const { row, bubble } = makeRow(who);
  bubble.innerHTML = marked.parse(text);
  chat.scrollTop = chat.scrollHeight;
  animateRowIn(row);              // 原来那行 anmie(...) 换成这个
  return { row, bubble };
}

export function addTyping() {
  const { row, bubble } = makeRow("ai");
  bubble.innerHTML = '<div class="typing"><i></i><i></i><i></i></div>';
  chat.scrollTop = chat.scrollHeight;
  animateRowIn(row, 12);          // 原来是 translateY:[12,0]，传 12
  animateTyping(bubble);          // 原来那个长 channels 数组换成这个
  return row;
}