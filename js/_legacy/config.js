/* config.js —— 配置与接线：API 地址 + DOM 元素引用 */

export const API = window.API_URL || "http://127.0.0.1:8000";

export const dot        = document.getElementById("dot");
export const statusText = document.getElementById("statusText");
export const chat       = document.getElementById("chat");
export const input      = document.getElementById("q");
export const sendBtn    = document.getElementById("send");
export const hello      = document.getElementById("hello");

