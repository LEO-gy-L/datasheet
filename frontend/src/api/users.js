import { USERS, delay } from "@/mock/data.js";
import { request } from "./client.js";

/**
 * 用户管理接口（管理员「用户管理 → 账号管理」页用）
 *
 * 【现在】读写内存里的假数据；【接后端后】换成注释里的 request(...)。
 * 注意这里的"改账号名"和"重置密码"是**管理员操作别人**，
 * 跟用户在「用户信息」页改自己的名字 / 密码是两套接口（那套在 api/auth.js）。
 */

const STORE = [...USERS];

/**
 * 用户列表。
 * @param {object} options keyword 模糊搜索（账号 / 名字 / 邮箱）
 * 【接后端后】return request(`/users?keyword=${encodeURIComponent(keyword ?? "")}`);
 */
export async function listUsers({ keyword } = {}) {
  let rows = [...STORE];
  if (keyword?.trim()) {
    const k = keyword.trim().toLowerCase();
    rows = rows.filter(
      (u) =>
        u.username.toLowerCase().includes(k) ||
        u.name.toLowerCase().includes(k) ||
        (u.email ?? "").toLowerCase().includes(k)
    );
  }
  return delay(rows);
}

/**
 * 改某个用户的账号名 / 名字 / 邮箱。
 * 【接后端后】return request(`/users/${id}`, { method: "PUT", body: patch });
 */
export async function updateUser(id, patch) {
  const row = STORE.find((u) => u.id === id);
  if (!row) throw new Error("用户不存在");
  Object.assign(row, patch);
  return delay({ ...row }, 280);
}

/**
 * 管理员重置某个用户的密码。
 * 为什么单独一个接口：重置密码通常要写单独的操作日志（谁在什么时候改了谁的密码），
 * 跟"改资料"不是一回事，混在一起以后审计会很难受。
 * 【接后端后】return request(`/users/${id}/password`, { method: "PUT", body: { password } });
 */
export async function resetPassword(id, password) {
  if (!password || password.length < 6) throw new Error("新密码至少 6 位");
  return delay({ id, ok: true }, 300);
}

/**
 * 启用 / 禁用账号。
 * 【接后端后】return request(`/users/${id}/status`, { method: "PUT", body: { status } });
 */
export async function setUserStatus(id, status) {
  const row = STORE.find((u) => u.id === id);
  if (row) row.status = status;
  return delay({ ...row }, 240);
}

// 接后端后删掉这行
void request;
