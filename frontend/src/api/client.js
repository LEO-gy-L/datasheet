/**
 * 请求层（全站唯一的网络出口）
 * ============================
 * 所有接口调用都必须走这里的 request() —— 好处是四件事只写一遍：
 *   ① 拼 base 路径（/api，开发时由 vite 代理转给 8000 端口）
 *   ② 自动带上登录 token
 *   ③ 统一把后端的各种错误格式，转成一句能直接显示给人看的中文
 *   ④ token 失效时统一清干净并广播出去（见下面 UNAUTHORIZED_EVENT）
 */

/** 后端地址前缀。开发时用 vite 代理，所以默认就是相对路径 /api */
const BASE = import.meta.env.VITE_API_BASE ?? "/api";

/**
 * token 存在**单独的 key** 里，不跟用户信息混着存。
 *
 * 为什么要分开：两者的生命周期不一样 ——
 *   用户信息会因为"改了名字 / 邮箱"而更新，token 不会；
 *   token 会因为过期而作废，用户信息不该跟着一起没。
 * 混在一个对象里存的话，改个名字就要记得把 token 原样带回去，漏一次就把人登出了。
 */
const TOKEN_KEY = "datasheet.token";

/**
 * 登录失效的广播事件名。
 *
 * 为什么用事件，而不是直接在下面跳转到登录页：
 *   这一层是纯网络层，不该知道"页面该怎么跳"（也没法用 useNavigate —— 它压根不是组件）。
 *   所以这里只负责"喊一声"，由 AuthContext 监听、清空登录态，
 *   路由守卫自然就会把人带到登录页 —— 职责不越界。
 *   将来想加"弹出重新登录弹窗"，改监听方就行，这一层不用动。
 */
export const UNAUTHORIZED_EVENT = "datasheet:unauthorized";

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
 *   body    对象会被 JSON.stringify；FormData 则原样发送（见下面说明）；不传就不带 body
 *   signal  AbortSignal，用于取消请求（比如用户快速连点两次时取消上一次）
 */
export async function request(path, { method = "GET", body, signal } = {}) {
  const headers = {};

  /* FormData 是个特例，必须区别对待：
     JSON 请求要自己写 Content-Type: application/json；
     但文件上传**不能手写** Content-Type —— 它长这样
         multipart/form-data; boundary=----WebKitFormBoundaryXXXX
     那串 boundary 是浏览器随机生成、用来分隔各个字段的，只有浏览器自己知道。
     手写了 Content-Type 就等于把这个参数抹掉，后端拿到一堆拼不起来的字节 ——
     表现为"文件字段是空的"这种很难查的症状。
     所以这里：是 FormData 就完全不设，交给浏览器自己填。 */
  const isFormData = typeof FormData !== "undefined" && body instanceof FormData;
  if (body !== undefined && !isFormData) headers["Content-Type"] = "application/json";

  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let res;
  try {
    res = await fetch(BASE + path, {
      method,
      headers,
      body: body === undefined ? undefined : isFormData ? body : JSON.stringify(body),
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
    /* 401 = 后端明确说"我不认识你是谁"（没登录，或 token 过期/被篡改）。
       这时候本地那份 token 已经没用了，留着只会让后面每个请求都失败一遍 ——
       所以就地清掉，并喊一声让 AuthContext 把登录态也清空。 */
    if (res.status === 401) {
      setToken("");
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    }
    throw new ApiError(readErrorMessage(data, res.status), res.status);
  }
  return data;
}

/**
 * 从各种可能的错误响应里，抠出一句能给人看的话。
 *
 * FastAPI 的报错有两种常见形态：
 *   {"detail": "没找到向量库"}                                  ← 我们自己抛的 HTTPException / 业务异常
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
