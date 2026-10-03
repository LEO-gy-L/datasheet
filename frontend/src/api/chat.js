import { request } from "./client.js";

/**
 * 问答接口
 * ========
 * ⚠️ 这是唯一一个**真接口**，不是假数据 —— 后端 /api/ask 已经做好了，
 *    直接打就能拿到真实答案（带出处页码）。
 *
 * 后端返回：
 *   {
 *     answer:  "……",          DeepSeek 生成的答案（markdown）
 *     sources: ["第 2 页", …], 答案来源的页码
 *     chunks:  [...],           命中的片段（调试用，页面可以不显示）
 *     seconds: 3.21             耗时
 *   }
 */

/**
 * 提问。
 *
 * @param {string} question 问题原文
 * @param {object} options
 *   signal: AbortSignal —— 用户连着问第二个问题时，用它取消上一个还没回来的请求，
 *           不然两个回答可能乱序插进对话里。
 */
export async function ask(question, { signal } = {}) {
  return request("/ask", {
    method: "POST",
    body: { question },
    signal,
  });
}

/** 后端是否活着（顶栏那个小圆点用它） */
export async function health() {
  return request("/health");
}
