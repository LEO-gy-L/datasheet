import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "@/context/AuthContext.jsx";

/**
 * 路由守卫
 * ========
 * 就是一个"包在页面外面的组件"：它先判断该不该放行，
 * 放行就把 children 原样渲染出去，不放行就换成一条 <Navigate> 让路由跳走。
 *
 * 为什么不用更"聪明"的做法（比如在 axios 拦截器里判断 401 就跳登录）：
 *   那样只能挡住"请求失败"，挡不住"用户直接在地址栏手输 /admin/users"。
 *   路由守卫是在渲染前就拦住，页面根本不会挂载，也就不会白跑一次请求。
 */

/** 某个角色登录成功后，默认该去的首页 */
export function homePathFor(role) {
  return role === "admin" ? "/admin/ingest" : "/assistant";
}

/**
 * @param {string} role 要求什么角色。不传 = 只要登录了就行
 */
export default function RequireAuth({ role, children }) {
  const { user } = useAuth();
  const location = useLocation();

  if (!user) {
    // 没登录 -> 去登录页，并把"原本想访问的地址"塞进 state。
    // 登录成功后会读它跳回去，这样点别人发的 /admin/users 链接也能直达。
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  if (role && user.role !== role) {
    // 登录了但角色不对（比如普通用户手输 /admin/ingest）。
    // 这里**送回他自己角色的首页**，而不是弹一个"无权限"的报错页 ——
    // 对用户来说"被弹回自己的地盘"比"看到一堵错误墙"体感好得多。
    return <Navigate to={homePathFor(user.role)} replace />;
  }

  return children;
}
