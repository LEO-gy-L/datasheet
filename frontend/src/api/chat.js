import { request } from "./client.js";

/**
 * 问答接口
 * ========
 * 后端 /api/ask（backend/app/api/qa.py）。
 *
 * 后端返回：
 *   {
 *     answer:  "……",          DeepSeek 生成的答案（markdown）
 *     sources: ["第 2 页", …], 答案来源的页码（其实形如 "xx.pdf 第 2 页"）
 *     seconds: 3.21             耗时
 *   }
 *
 * ⚠️ 2026-10-03 起，这个接口**需要登录** ——
 *    后端答完会把这一轮写进问答历史，得知道是谁问的。
 *    token 由 client.js 自动带上，调用方不用管。
 */
export async function ask(question, { source, signal } = {}) {
  return request("/ask", {
    method: "POST",
    body: {
      question,
      // source = 限定只在这一份手册里检索（助理页选择器选的那个文件名）。
      // 不选时不传，JSON.stringify 会直接省略这个键，后端收到 None = 在全部手册里检索。
      source,
    },
    signal,
  });
}

/** 后端是否活着（顶栏那个小圆点用它） */
export async function health() {
  return request("/health");
}
