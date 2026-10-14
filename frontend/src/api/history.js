import { request } from "./client.js";

/**
 * 问答历史接口
 * ============
 * 后端在 backend/app/api/history.py。
 *
 * ⚠️ 这里**没有 create** —— 历史不是前端"提交"的，
 *    而是 /api/ask 答完之后**后端自己**写进去的。
 *    这样设计的原因：如果让前端提交，用户就能伪造"我问过什么"，
 *    而且得信任前端传来的答案内容（那本来是我们自己生成的，没必要绕一圈）。
 *
 * ⚠️ 这里也**没有传 userId 的参数** —— 谁能看到谁的数据，完全由 token 决定。
 *    接口签名上就不给"查别人"的可能性，比"记得在每个函数里加一句权限判断"可靠得多。
 */

/**
 * 我的历史列表，按时间倒序。
 *
 * @param {object} options
 *   keyword  按问题内容模糊搜
 *   limit    一次取多少条（默认 50，后端上限 200）
 *   offset   跳过多少条（分页用：取第二页就传 offset=50）
 */
export async function listHistory({ keyword, limit = 50, offset = 0 } = {}) {
  const qs = new URLSearchParams();
  if (keyword?.trim()) qs.set("keyword", keyword.trim());
  qs.set("limit", String(limit));
  qs.set("offset", String(offset));
  return request(`/history?${qs}`);
}

/** 删一条。只能删自己的 —— 后端会把 user_id 一起作为查询条件。 */
export async function deleteHistory(id) {
  return request(`/history/${id}`, { method: "DELETE" });
}

/** 清空我的全部历史。返回 { ok, count }，count 是删掉的条数。 */
export async function clearHistory() {
  return request("/history", { method: "DELETE" });
}
