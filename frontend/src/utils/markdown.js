import DOMPurify from "dompurify";
import { marked } from "marked";

/**
 * markdown -> 安全的 HTML
 * =======================
 * 模型输出的答案是 markdown（带表格、代码块、列表），要交给
 * React 的 dangerouslySetInnerHTML 渲染 —— 那个属性名就是在警告：
 * **传进去的东西会被当 HTML 执行**。
 *
 * 所以 DOMPurify 这一层是必需的，不是保险起见：
 *   模型可能被用户的问题"带跑"，输出一行 <script> 或 <img onerror=...>。
 *   没有这层过滤，那就是标准的 XSS 漏洞 —— 用户 A 的问题能让用户 B 的浏览器
 *   执行任意 JS（偷 token、改页面、发请求）。
 *
 * 为什么返回值是 { __html: ... } 这种奇怪的形状：
 *   React 规定 dangerouslySetInnerHTML 必须传这个对象，见
 *   <div dangerouslySetInnerHTML={toHtml(text)} /> 。
 *
 * 抽成公共模块的原因：助理页和历史问答页都要渲染同一批答案，
 * 两处各写一份的话，将来"忘了在其中一处加 sanitize"就是个真漏洞。
 */
export function toHtml(text) {
  return { __html: DOMPurify.sanitize(marked.parse(text ?? "")) };
}
