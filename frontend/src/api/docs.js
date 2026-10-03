import { DOCUMENTS, delay } from "@/mock/data.js";
import { request } from "./client.js";

/**
 * 文档 / 入库接口（管理员「入库」页用）
 * ===================================
 * 【现在】读 mock/data.js 里的假列表。
 * 【接后端后】把每个函数体换成文件里标注的那行 request(...)。
 *
 * 入库为什么是"两个动作"而不是一个：
 *   上传（uploadDocument）只是把 PDF 存到服务器磁盘，很快；
 *   建库（indexDocument）要解析 PDF -> 切块 -> 调智谱 embedding 向量化，
 *   慢（几百块要几十秒到几分钟）而且**花钱**。
 *   合成一个接口的话，上传按钮会一直转圈转到你怀疑人生。
 *   所以拆开：上传完列表里多一行（状态"未入库"），再点"重新入库"才真的开始跑。
 */

/** 文档列表 */
export async function listDocuments() {
  /* 【接后端后】return request("/documents"); */
  return delay([...DOCUMENTS]);
}

/**
 * 上传一个文件（不建库）。
 * 【接后端后】
 *   const form = new FormData();
 *   form.append("file", file);
 *   return request("/documents/upload", { method: "POST", body: form });
 * ⚠️ 注意：那时 client.js 的 request 要支持 FormData
 *    （不能设 Content-Type，让浏览器自己带 boundary）—— 到时候再改那一处。
 */
export async function uploadDocument(file) {
  return delay(
    {
      id: Date.now(),
      name: file.name,
      size: file.size,
      type: (file.name.split(".").pop() || "").toLowerCase(),
      indexed: false,
      pages: 0,
      chunks: 0,
    },
    400
  );
}

/**
 * 触发建库。
 * 【接后端后】return request(`/documents/${id}/index`, { method: "POST" }); ——
 *   注意这个接口会很慢，后端要么改成后台任务 + 轮询进度，要么前端用长超时。
 */
export async function indexDocument(id) {
  return delay({ id, ok: true }, 600);
}

/** 删除文档 */
export async function deleteDocument(id) {
  /* 【接后端后】return request(`/documents/${id}`, { method: "DELETE" }); */
  return delay({ id, ok: true }, 300);
}
