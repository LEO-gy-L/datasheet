import { Layout as AntLayout } from "antd";
import { Outlet } from "react-router-dom";

import Sidebar from "@/components/Sidebar.jsx";
import Topbar from "@/components/Topbar.jsx";

const { Header, Sider, Content } = AntLayout;

/**
 * 统一骨架：顶栏（全宽）+ 左侧菜单 + 内容区
 *
 *   ┌──────────────────────────────────┐
 *   │ 顶栏：logo · 标题        后端状态 · 头像 │
 *   ├────────┬─────────────────────────┤
 *   │ 侧栏菜单 │ 内容区 <Outlet />        │
 *   └────────┴─────────────────────────┘
 *
 * 管理员和普通用户**共用这一个 Layout**，区别只在侧栏里渲染哪套菜单
 * （Sidebar 内部按 user.role 取 menuFor(role)）。
 * 为什么不拆成两个 Layout：那样顶栏、头像菜单、状态检测的代码要抄两份，
 * 以后改一处忘一处。
 *
 * 高度用 100vh + flex，让「顶栏和侧栏固定、只有内容区滚动」——
 * 而不是整页滚动。整页滚动的话，内容长了以后侧栏会跟着滚走，很难看。
 *
 * 视觉上这里只做一件事：**用 1px 细线把三块分开**。
 * 顶栏和侧栏都是白底，内容区是浅灰底，靠色差和细线分层，
 * 不画任何阴影 —— 阴影一多就不"贵"了。
 */
export default function Layout() {
  return (
    <AntLayout style={{ height: "100vh" }}>
      <Header
        style={{
          height: 56,
          lineHeight: "56px",
          padding: "0 20px",
          flex: "0 0 56px",
          borderBottom: "1px solid var(--line)",
          display: "flex",
          alignItems: "center",
          zIndex: 10,
        }}
      >
        <Topbar />
      </Header>

      <AntLayout style={{ flex: 1, minHeight: 0 }}>
        <Sider
          width={220}
          theme="light"
          style={{ borderRight: "1px solid var(--line)", overflowY: "auto" }}
        >
          <Sidebar />
        </Sider>

        {/* minHeight:0 是 flex 布局的经典坑：
            不写它，子元素会按内容撑开，overflow:auto 就永远不触发，
            长内容会把整个页面顶长。 */}
        {/* padding 用 24 而不是 20：留白是"高级感"最便宜的来源 */}
        <Content style={{ padding: 24, overflowY: "auto", minHeight: 0 }}>
          <Outlet />
        </Content>
      </AntLayout>
    </AntLayout>
  );
}
