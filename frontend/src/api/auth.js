import { ACCOUNTS, delay } from "@/mock/data.js";
import { request, setToken } from "./client.js";

/**
 * 认证相关接口
 * ============
 * 【现在】只做前端：在本地账号表里比对，不发网络请求。
 * 【接后端后】把每个函数体里 return 后面那一行换掉即可，
 *            返回结构是照着"以后接口会长什么样"定的，页面代码不用动。
 *
 * 注意最下面那行 `void request;` —— 它只是为了防止 ESLint 报
 * "request 导入了却没用到"。接后端后删掉那行，把上面的 mock 换成真调用。
 */

/**
 * 登录。
 *
 * 返回：{ username, name, role, email, token }
 *   role 只有两种取值：'admin'（管理员）| 'user'（普通用户），
 *   路由守卫和侧边栏菜单都靠它来分叉。
 */
export async function login(username, password) {
  /* 【接后端后】换成：
     return request("/auth/login", { method: "POST", body: { username, password } });
  */
  return mockLogin(username, password);
}

/**
 * 本地版登录：拿账号密码去 ACCOUNTS 里找完全匹配的一条。
 *
 * 为什么包一层 Promise 还要故意加 260ms 延迟：
 *   不加延迟的话，"点登录 -> 瞬间跳转"，你就永远看不到按钮的 loading 态，
 *   等真接上后端才发现 loading 早写错了。先把异步路径跑真，后面才不出岔子。
 */
function mockLogin(username, password) {
  return new Promise((resolve, reject) => {
    setTimeout(() => {
      const hit = ACCOUNTS.find(
        (a) => a.username === username.trim() && a.password === password
      );
      if (!hit) {
        reject(new Error("账号或密码不对"));
        return;
      }
      // 用解构把 password 摘出去，避免密码被写进 localStorage
      const { password: _omit, ...safe } = hit;
      resolve({ ...safe, token: `mock-token-${hit.username}` });
    }, 260);
  });
}

/** 退出 / 切换账户：清掉本地凭证即可，后端阶段才需要通知服务端作废 token */
export function logout() {
  /* 【接后端后】前面补一行：
     request("/auth/logout", { method: "POST" }).catch(() => {});
     （加 catch 是因为"作废 token 失败"不该拦住用户退出，本地照样要清干净） */
  setToken("");
}

/**
 * 修改密码。
 * 【接后端后】return request("/auth/password", { method: "PUT", body: { oldPassword, newPassword } });
 */
export async function changePassword({ oldPassword, newPassword }) {
  if (!oldPassword || !newPassword) throw new Error("旧密码和新密码都要填");
  if (newPassword.length < 6) throw new Error("新密码至少 6 位");
  return delay({ ok: true }, 320);
}

/**
 * 改自己的名字 / 邮箱。
 * 【接后端后】return request("/auth/profile", { method: "PUT", body: { name, email } });
 */
export async function updateProfile({ name, email }) {
  if (!name || !name.trim()) throw new Error("名字不能为空");
  return delay({ ok: true, name: name.trim(), email }, 320);
}

// 接后端后删掉这行（见文件头说明）
void request;
