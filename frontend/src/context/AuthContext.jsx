import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { login as apiLogin, logout as apiLogout, me as apiMe } from "@/api/auth.js";
import { UNAUTHORIZED_EVENT, getToken } from "@/api/client.js";

/**
 * 全局登录态
 * ==========
 * 为什么用 Context 而不是把 user 塞到每个页面自己的 state 里：
 *   "当前是谁登录的"这件事，顶栏（显示名字）、侧栏（显示哪套菜单）、
 *   路由守卫（能不能进这个页面）都要用。三处都要用同一份数据 ——
 *   Context 就是 React 里干这个的。
 *
 * ---------------------------------------------------------------------------
 * 【2026-10-03 接后端后的两个变化】
 *
 * ① 启动时要跟后端核对一次（下面第一个 useEffect）
 *    localStorage 里那份用户信息是**上一次登录时的快照**，它可能已经过时：
 *      · token 过期了（默认 12 小时）—— 这时本地看起来还"登录着"，实际已经没用了
 *      · 管理员改了你的名字 / 邮箱
 *      · 账号被禁用了
 *    所以挂载后拿本地 token 调一次 /auth/me，以服务端为准。
 *
 *    ⚠️ 但**初值仍然从 localStorage 读**，不做"校验完再渲染"的等待态 ——
 *       否则每次刷新页面都会先白屏一下（首页闪登录页再闪回来，很难看）。
 *       代价是"token 已失效时，界面会先按已登录显示、随即被踢回登录页"，
 *       这个闪动只有 token 过期时才会出现，可以接受。
 *
 * ② 监听 401 广播（下面第二个 useEffect）
 *    token 在**使用过程中**失效（比如后端重启换了密钥）时，client.js 会清掉本地
 *    token 并广播一个事件。这里收到就把 user 也清掉，路由守卫自然把人带回登录页。
 *    为什么不让 client.js 自己跳转：那层是网络层，不该知道页面怎么跳（见 client.js 注释）。
 */
const STORAGE_KEY = "datasheet.auth";

const AuthContext = createContext(null);

/** 读本地缓存的用户快照。解析失败一律当作"没登录"。 */
function readStoredUser() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    // localStorage 被人手改坏、或者存进去的不是 JSON —— 不能让整个应用起不来
    return null;
  }
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(readStoredUser);

  // user 一变就同步写回 localStorage
  useEffect(() => {
    if (user) localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
    else localStorage.removeItem(STORAGE_KEY);
  }, [user]);

  /* ---------- 启动时：拿 token 跟后端核对"我是谁" ---------- */
  useEffect(() => {
    // 本地根本没有 token，就没有可核对的东西（也省掉一次必然 401 的请求）
    if (!getToken()) {
      setUser(null);
      return;
    }

    /* cancelled 是防"组件已卸载但请求才回来"：
       回调里 setUser 一个已经卸载的组件会报警告，逻辑上也可能是脏数据。
       （严格来说这个 Provider 在应用生命周期里不会卸载，但写上是对的，
         以后如果有人把它挪进某个会切走的布局里，这里不会突然出问题。） */
    let cancelled = false;
    apiMe()
      .then((fresh) => {
        if (!cancelled) setUser(fresh);
      })
      .catch(() => {
        /* 什么都不做是**故意的**：
             · token 失效 -> client.js 已经清掉 token 并广播了 UNAUTHORIZED_EVENT，
               下面的监听器会把 user 清空，不用在这里重复处理
             · 后端没启动（连不上）-> 本地这份信息其实还是有效的，
               不该因为"服务暂时连不上"就把人登出 —— 他启动后端刷新一下就好了 */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  /* ---------- 运行中：收到 401 广播就清登录态 ---------- */
  useEffect(() => {
    const onUnauthorized = () => setUser(null);
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    // 清理函数：不加的话，这个 Provider 每次重新挂载都会叠一个监听器（内存泄漏）
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  const login = useCallback(async (username, password) => {
    // apiLogin 内部已经把 token 存好了，这里拿到的就是纯用户信息
    const next = await apiLogin(username, password);
    setUser(next);
    return next;
  }, []);

  /** 退出登录：清掉凭证和内存里的用户 */
  const logout = useCallback(() => {
    apiLogout();
    setUser(null);
  }, []);

  /**
   * 「切换登录」：跟退出登录本质一样（都是先清空），
   * 单独留一个名字是因为语义不同 —— 退出后前端会跳首页，
   * 切换登录后要跳到登录页并且**不要**自动跳回原页面。
   */
  const switchAccount = useCallback(() => {
    apiLogout();
    setUser(null);
  }, []);

  /** 改了名字 / 邮箱之后，同步更新全局状态（否则顶栏还显示旧名字） */
  const updateProfile = useCallback((patch) => {
    setUser((prev) => (prev ? { ...prev, ...patch } : prev));
  }, []);

  const value = useMemo(
    () => ({
      user,
      isAdmin: user?.role === "admin",
      login,
      logout,
      switchAccount,
      updateProfile,
    }),
    [user, login, logout, switchAccount, updateProfile]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/** 在组件里这样用：const { user, logout } = useAuth(); */
export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth() 必须在 <AuthProvider> 内部使用");
  return ctx;
}
