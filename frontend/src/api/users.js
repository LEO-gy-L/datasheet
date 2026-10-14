import { request } from "./client.js";

/**
 * 用户管理接口（管理员「用户管理 → 账号管理」页用）
 * ===============================================
 * 【2026-10-03】从 mock 换成真后端，后端在 backend/app/api/users.py。
 *
 * ⚠️ 这里全是**管理员操作别人**的接口，跟用户在「用户信息」页
 *    改自己的名字 / 密码（那套在 api/auth.js）是两回事。
 *    最直观的区别：改别人的密码**不需要**提供旧密码。
 *
 * 四个接口都需要管理员身份 —— 后端会校验（普通用户调用直接 403），
 * 前端不用做任何权限判断：**权限是服务端的事，前端只管调**
 * （前端判断一次只是为了少一次无效请求，绝不能当安全措施）。
 */

/**
 * 用户列表。
 * @param {object} options keyword 模糊搜索（账号 / 名字 / 邮箱）
 */
export async function listUsers({ keyword } = {}) {
  const qs = new URLSearchParams();
  if (keyword?.trim()) qs.set("keyword", keyword.trim());
  const q = qs.toString();
  return request(`/users${q ? `?${q}` : ""}`);
}

/**
 * 改某个用户的账号名 / 名字 / 邮箱。
 *
 * ⚠️ 只传要改的字段就行（后端用 exclude_unset 区分"没传"和"传了空值"）。
 *    这里会把整个表单的三个字段都传过去，是没问题的 ——
 *    因为它们本来就是"用户改了什么就是什么"。
 *
 * 返回更新后的完整用户对象，页面直接replace掉表格里那一行即可。
 */
export async function updateUser(id, patch) {
  return request(`/users/${id}`, { method: "PUT", body: patch });
}

/**
 * 管理员重置某个用户的密码。
 *
 * 为什么单独一个接口：重置密码是敏感操作，将来要单独记操作日志
 * （谁在什么时候改了谁的密码），跟"改资料"不是一回事。
 *
 * 这也是整个系统里**唯一**的"忘记密码"通道 —— 用户忘了密码
 * 只能找管理员重置，因为"证明你是本人"这件事前端做不到
 * （需要邮箱验证码 / 密保问题之类的额外设施）。
 */
export async function resetPassword(id, password) {
  if (!password || password.length < 6) throw new Error("新密码至少 6 位");
  return request(`/users/${id}/password`, { method: "PUT", body: { password } });
}

/**
 * 启用 / 禁用账号。
 * @param {string} status 'active' | 'disabled'
 *
 * 后端有两条自我保护规则，触发时会返回 409 并带一句中文说明：
 *   ① 不能禁用当前登录的账号（否则立刻把自己踢出去）
 *   ② 不能禁用最后一个可用管理员（否则整个系统再没人能进后台）
 */
export async function setUserStatus(id, status) {
  return request(`/users/${id}/status`, { method: "PUT", body: { status } });
}
