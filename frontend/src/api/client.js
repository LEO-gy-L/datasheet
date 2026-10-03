/**
 * 请求层（全站唯一的网络出口）
 * ============================
 * 所有接口调用都必须走这里的 request() —— 好处是三件事只写一遍：
 *   ① 拼 base 路径（/api，开发时由 vite 代理转给 8000 端口）
 *   ② 自动带上登录 token
 *   ③ 统一把后端的各种错误格式，转成一句能直接显示给人看的中文
 */

/** 后端地址前缀。开发时用 vite 代理，所以默认就是相对路径 /api */
const BASE = import.meta.env.VITE_API_BASE ?? "/api";

const TOKEN_KEY = "datasheet.token";

/** 自定义错误类型，方便页面区分"网络断了"和"接口报错" */
export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

/**
 * 发一个请求。
 *
 * @param {string} path   以 / 开头的接口路径，例如 "/ask"
 * @param {object} options
 *   method  GET / POST / PUT / DELETE
 *   body    会被 JSON.stringify 的对象；不传就不带 body
 *   signal  AbortSignal，用于取消请求（比如用户快速连点两次时取消上一次）
 */
export async function request(path, { method = "GET", body, signal } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let res;
  try {
    res = await fetch(BASE + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (err) {
    // fetch 只有在"根本没连上"时才抛异常（后端没启动、断网、被取消）
    if (err?.name === "AbortError") throw err;
    throw new ApiError("连不上后端服务，请先双击 start_backend.bat 启动", 0);
  }

  // 先按文本读，再尝试当 JSON 解析。
  // 为什么不直接 res.json()：后端 500 时可能返回一段 HTML 错误页，
  // 直接 json() 会在解析处再抛一次异常，把真正的错误信息盖掉。
  const text = await res.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { raw: text };
    }
  }

  if (!res.ok) {
    throw new ApiError(readErrorMessage(data, res.status), res.status);
  }
  return data;
}

/**
 * 从各种可能的错误响应里，抠出一句能给人看的话。
 *
 * FastAPI 的报错有两种常见形态：
 *   {"detail": "没找到向量库"}                                  ← 我们自己抛的 HTTPException
 *   {"detail": [{"loc": [...], "msg": "field required", ...}]}   ← Pydantic 参数校验失败
 * 两种都要能认出来，否则用户只会看到一句"请求失败（HTTP 422）"，完全不知道哪里填错了。
 */
function readErrorMessage(data, status) {
  const detail = data?.detail ?? data?.message ?? data?.error;

  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0];
    if (typeof first === "string") return first;
    if (first?.msg) return first.msg;
  }
  return `请求失败（HTTP ${status}）`;
}
