import { LogoutOutlined, SwapOutlined, UserOutlined } from "@ant-design/icons";
import { App, Avatar, Dropdown } from "antd";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/context/AuthContext.jsx";

/**
 * 右上角头像 + 下拉菜单（三项：切换登录 / 账号名 / 退出登录）
 *
 * 「切换登录」和「退出登录」的差别（行为上很像，但体验上不是一回事）：
 *   退出登录   -> 弹确认框，确认后回登录页。防误点。
 *   切换登录   -> 不弹确认，直接清空当前登录态回登录页，
 *                目的是"换个人登"（比如普通用户想登管理员账号看看后台）。
 *                所以它不该有"你确定要退出吗"这种吓人的措辞。
 *
 * 配色：头像改成深灰阶（管理员 #18181B、普通用户 #3F3F46），
 * 靠深浅区分角色而不是靠颜色 —— 这是灰阶系统里表达"角色不同"的办法。
 */
export default function AccountMenu() {
  const { user, isAdmin, logout, switchAccount } = useAuth();
  const navigate = useNavigate();
  // 从 <App> 里取 message / modal，这样它们跟着主题走，也不会有静态方法警告
  const { message, modal } = App.useApp();

  if (!user) return null;

  const items = [
    { key: "switch", icon: <SwapOutlined />, label: "切换登录" },
    {
      key: "account",
      icon: <UserOutlined />,
      // 把当前账号名直接写在菜单里，省得点进去才知道自己是谁
      label: `账号名：${user.name || user.username}`,
    },
    { type: "divider" },
    { key: "logout", icon: <LogoutOutlined />, label: "退出登录", danger: true },
  ];

  function onSelect({ key }) {
    if (key === "switch") {
      switchAccount();
      navigate("/login", { replace: true });
      message.info("请用其他账号登录");
      return;
    }

    if (key === "account") {
      // 账号名那一项：跳到自己的"信息"页，在那里改名字 / 改密码
      navigate(isAdmin ? "/admin/profile" : "/profile");
      return;
    }

    if (key === "logout") {
      modal.confirm({
        title: "确认退出登录？",
        content: "退出后需要重新输入账号密码。",
        okText: "退出",
        okButtonProps: { danger: true },
        cancelText: "取消",
        onOk() {
          logout();
          navigate("/login", { replace: true });
        },
      });
    }
  }

  return (
    <Dropdown menu={{ items, onClick: onSelect }} placement="bottomRight" trigger={["click"]}>
      {/* hover 时的浅灰底写在 global.css 的 .account-trigger 里 ——
          内联 style 没法写 :hover */}
      <div
        className="account-trigger"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          cursor: "pointer",
          padding: "4px 8px",
        }}
      >
        <Avatar
          size={28}
          style={{
            background: isAdmin ? "#18181B" : "#3F3F46",
            fontSize: 13,
            flex: "0 0 28px",
          }}
        >
          {(user.name || user.username || "?").slice(0, 1)}
        </Avatar>
        <span style={{ fontSize: 13.5, color: "var(--ink)", whiteSpace: "nowrap" }}>
          {user.name || user.username}
        </span>
        <span style={{ fontSize: 9, color: "var(--ink-faint)", lineHeight: 1 }}>▼</span>
      </div>
    </Dropdown>
  );
}
