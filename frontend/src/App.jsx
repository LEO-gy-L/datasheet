import { Navigate, Route, Routes } from "react-router-dom";

import { useAuth } from "@/context/AuthContext.jsx";
import Layout from "@/layouts/Layout.jsx";
import RequireAuth, { homePathFor } from "@/router/guard.jsx";

import ChangePassword from "@/views/ChangePassword.jsx";
import Login from "@/views/Login.jsx";
import Profile from "@/views/Profile.jsx";
import AdminFeedback from "@/views/admin/Feedback.jsx";
import Ingest from "@/views/admin/Ingest.jsx";
import Users from "@/views/admin/Users.jsx";
import Assistant from "@/views/user/Assistant.jsx";
import UserFeedback from "@/views/user/Feedback.jsx";

/**
 * 路由表（全站唯一的"哪个地址显示哪个页面"的定义处）
 *
 * 结构说明：
 *   外层那条**没有 path 的 Route** 是 React Router v6 的"布局路由"写法。
 *   它把 <Layout /> 当成所有子路由的外壳 —— 于是切页面时顶栏和侧栏不会重新挂载，
 *   只有中间内容区在变（这也是为什么侧边栏菜单点起来"不闪"）。
 *   Layout 内部要写 <Outlet />，那才是子页面渲染的位置。
 *
 * 权限分两段：admin 一组、user 一组，各自套自己的 RequireAuth。
 */
export default function App() {
  return (
    <Routes>
      {/* 登录页：不需要登录就能进，否则会死循环 */}
      <Route path="/login" element={<Login />} />

      {/* ---------- 管理员 ---------- */}
      <Route
        element={
          <RequireAuth role="admin">
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/admin/ingest" element={<Ingest />} />
        <Route path="/admin/users" element={<Users />} />
        <Route path="/admin/users/feedback" element={<AdminFeedback />} />
        <Route path="/admin/profile" element={<Profile />} />
        {/* 改密码页**不进左侧菜单**（菜单只留三个词条），
            从「管理员信息」底部的链接进来。两级地址沿用 /admin/xxx 的写法。 */}
        <Route path="/admin/password" element={<ChangePassword />} />
      </Route>

      {/* ---------- 普通用户 ---------- */}
      <Route
        element={
          <RequireAuth role="user">
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/assistant" element={<Assistant />} />
        <Route path="/feedback" element={<UserFeedback />} />
        <Route path="/profile" element={<Profile />} />
        <Route path="/profile/password" element={<ChangePassword />} />
      </Route>

      {/* 其他任何地址（包括 "/"）：按登录状态和角色决定去哪 */}
      <Route path="*" element={<HomeRedirect />} />
    </Routes>
  );
}

function HomeRedirect() {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  return <Navigate to={homePathFor(user.role)} replace />;
}
