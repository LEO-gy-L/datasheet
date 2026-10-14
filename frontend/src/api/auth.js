import { request, setToken } from "./client.js";

/**
 * 认证相关接口
 * ============
 * 【2026-10-03】从 mock 换成真后端。后端在 backend/app/api/auth.py。
 *
 * 页面代码（Login.jsx / Profile.jsx / ChangePassword.jsx）**一行都没改** ——
 * 因为这套函数的名字、参数、返回结构在写 mock 的那天就照着
 * "以后接口会长什么样"定好了。这就是当初那层 mock 的作用。
 */

/**
 * 登录。
 *
 * 返回：{ id, username, name, role, email, status, createdAt, lastLogin }
 *   ⚠️ **不含 token** —— token 由本函数就地存进 localStorage，不往外传。
 *      为什么这样设计：AuthContext 会把返回的这坨对象整个存进 localStorage
 *      当作"当前用户"，如果 token 也在里面，等于同一份凭证存了两处，
 *      清理时就要记得清两处（漏一处就是"登出后还能用旧凭证"的安全问题）。
 *
 * role 只有两种取值：'admin'（管理员）| 'user'（普通用户），
 * 路由守卫和侧边栏菜单都靠它来分叉。
 */
export async function login(username, password) {
  const data = await request("/auth/login", {
    method: "POST",
    body: { username, password },
  });

  setToken(data.token);

  // 用解构把 token 摘出去（跟当初 mock 版摘掉 password 是同一个理由）
  const { token: _token, ...user } = data;
  return user;
}

/**
 * 拿当前登录用户。
 *
 * 用途：应用启动时调一次，拿本地存的 token 去问后端"它还有效吗、我是谁"。
 * 解决的问题：token 可能已经过期（默认 12 小时），或者管理员改过你的名字 ——
 * 光看 localStorage 里那份副本是不知道的。
 */
export async function me() {
  return request("/auth/me");
}

/** 退出 / 切换账户：通知后端 + 清掉本地凭证。 */
export function logout() {
  /* 加 .catch 是刻意的：后端暂时连不上时，"通知服务端"这件事失败
     不该拦住用户退出 —— 本地凭证照样要清干净，否则他就被卡在登录态里出不去了。
     （后端那个接口其实什么也不做，只返回 ok，原因见 api/auth.py 的注释） */
  request("/auth/logout", { method: "POST" }).catch(() => {});
  setToken("");
}

/**
 * 修改密码。
 * ⚠️ 后端会再校验一次"新密码至少 6 位"，这里的前端校验只是为了让用户
 *    不用等一个来回就知道填错了。
 */
export async function changePassword({ oldPassword, newPassword }) {
  if (!oldPassword || !newPassword) throw new Error("旧密码和新密码都要填");
  if (newPassword.length < 6) throw new Error("新密码至少 6 位");
  return request("/auth/password", {
    method: "PUT",
    body: { oldPassword, newPassword },
  });
}

/**
 * 改自己的名字 / 邮箱。
 * 返回更新后的用户信息（页面拿它同步顶栏显示的名字）。
 */
export async function updateProfile({ name, email }) {
  if (!name || !name.trim()) throw new Error("名字不能为空");
  return request("/auth/profile", { method: "PUT", body: { name, email } });
}
