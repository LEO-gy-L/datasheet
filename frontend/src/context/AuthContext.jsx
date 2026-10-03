import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { login as apiLogin, logout as apiLogout } from "@/api/auth.js";

/**
 * 全局登录态
 * ==========
 * 为什么用 Context 而不是把 user 塞到每个页面自己的 state 里：
 *   "当前是谁登录的"这件事，顶栏（显示名字）、侧栏（显示哪套菜单）、
 *   路由守卫（能不能进这个页面）都要用。三处都要用同一份数据 ——
 *   Context 就是 React 里干这个的。
 *
 * 登录态存 localStorage，所以刷新页面不会掉登录。
 */

const STORAGE_KEY = "datasheet.auth";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  // 初始化函数里读 localStorage：这样首次渲染就已经是"登录状态"，
  // 不会先闪一下登录页再跳回来。
  const [user, setUser] = useState(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  });

  // user 一变就同步写回 localStorage
  useEffect(() => {
    if (user) localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
    else localStorage.removeItem(STORAGE_KEY);
  }, [user]);

  const login = useCallback(async (username, password) => {
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
