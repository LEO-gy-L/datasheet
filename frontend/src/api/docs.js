import { request } from "./client.js";

/**
 * 文档 / 入库接口
 * ===============
 * 【2026-10-03 P5 完成】从 mock 换成真接口。
 * 后端：backend/app/api/documents.py
 *
 * 入库为什么还是"两个动作"而不是一个（这个设计没变）：
 *   上传（uploadDocument）只是把 PDF 存到服务器磁盘，很快；
 *   建库（indexDocument）要解析 PDF -> 切块 -> 调智谱 embedding 向量化，
 *   慢（几百块要几十秒到十几分钟）而且**花钱**。
 *   合成一个接口的话，上传按钮会一直转圈转到你怀疑人生，
 *   而且传错文件时钱已经花掉了、来不及反悔。
 *
 * 建库是**异步**的（这是 P5 相较原设计最大的变化）：
 *   POST /documents/{id}/index 会**立刻**返回（不到一秒），
 *   真正的活儿跑在后端的后台线程里。
 *   前端拿到响应后改成每 2 秒问一次进度 —— 轮询逻辑在 Ingest.jsx 里。
 *   为什么不在这里封装成一个"等它跑完"的 Promise：
 *     建库要十几分钟，一个十几分钟不 resolve 的 Promise 会占着内存，
 *     中途刷新页面就丢了；而且用户看不到进度，只会觉得卡死。
 *   **进度的本质是"多次观察"，不是"等一个结果"**，所以要暴露成轮询。
 */

/** 文档列表（管理员）。每行带 status / progress / error，够渲染整张表 */
export async function listDocuments() {
  return request("/documents");
}

/**
 * 上传一个 PDF（**不建库**）。
 *
 * ⚠️ 这里必须用 FormData，不能自己设 Content-Type。
 *    文件上传的请求头长这样：
 *        multipart/form-data; boundary=----WebKitFormBoundaryXXXX
 *    那串 boundary 是浏览器随机生成、用来分隔各个字段的，只有它自己知道。
 *    手写 Content-Type 就等于把这个参数抹掉，后端收到一堆拼不起来的字节 ——
 *    症状是"文件字段是空的"，非常难查。
 *    这件事已经统一处理在 client.js 的 request() 里了（见那边的 isFormData 分支），
 *    所以这里只要老老实实传一个 FormData 就好。
 */
export async function uploadDocument(file) {
  const form = new FormData();
  // 字段名必须是 "file" —— 后端签名是 `file: UploadFile = File(...)`，
  // 名字对不上时会返回 422（unprocessable entity），报错信息里带 field required。
  form.append("file", file);
  return request("/documents/upload", { method: "POST", body: form });
}

/**
 * 触发建库。**立刻返回**，不要 await 它的"结果"，它没有结果。
 *
 * 真正要关心的是后端有没有把它接住 —— 如果这份手册已经在建库了，
 * 这里会抛一个 409（ApiError.status === 409），页面据此提示"正在建库"。
 */
export async function indexDocument(id) {
  return request(`/documents/${id}/index`, { method: "POST" });
}

/** 单份手册的建库进度（轮询用）。只查一条主键，比拉整个列表轻 */
export async function documentProgress(id) {
  return request(`/documents/${id}/progress`);
}

/** 删除文档（会同时把它贡献的块从向量库里摘掉） */
export async function deleteDocument(id) {
  return request(`/documents/${id}`, { method: "DELETE" });
}

/**
 * 助理页 PDF 选择器的选项 —— **只返回已入库的手册**。
 *
 * 这个接口是文档相关里唯一对**普通用户**开放的（其余都要管理员）：
 *   用户要用"只在这份手册里提问"这个功能，就得知道有哪些手册可选；
 *   但服务器上有什么文件、哪份建库失败了，这些属于运维信息，不该给他看。
 */
export async function documentOptions() {
  return request("/documents/options");
}
