import {
  CommentOutlined,
  IdcardOutlined,
  RobotOutlined,
  TeamOutlined,
  UploadOutlined,
  UserOutlined,
} from "@ant-design/icons";

/**
 * 菜单配置（全站唯一的一份）。
 *
 * 这个模块对外只暴露**一个函数**：`menuFor(role)`。
 * 两份菜单数组故意不导出 —— 导出就等于承诺"外部可以依赖它的形状"，
 * 以后想加字段、改层级都要顾及外部；而现在想改随时能改。
 * （判断依据：全项目搜一遍，除了本文件没有人 import 它们。）
 *
 * 为什么单独抽一个文件而不是写死在 Sidebar 里：
 *   侧边栏渲染要用它，路由守卫判断"这个角色能不能进哪个页面"也要用它。
 *   两处用到同一份数据，放一起才不会改一处漏两处。
 *
 * key 就是路由路径 —— 这样 onSelect 时可以直接 navigate(key)，不用再维护一张映射表。
 *
 * 注意：菜单里**故意**不包含 `/admin/password`、`/profile/password` 这些子页面 ——
 * 它们是"从信息页点进去"的次级页面，出现在左侧菜单里反而会让词条变多、变乱。
 * 但它们仍要有高亮，靠的是 Sidebar.jsx 里的那个"子页面 → 归属菜单项"映射。
 */

/** 管理员：入库 / 用户管理（二级）/ 管理员信息 */
const ADMIN_MENU = [
  { key: "/admin/ingest", icon: <UploadOutlined />, label: "入库" },
  {
    key: "grp-users",
    icon: <TeamOutlined />,
    label: "用户管理",
    children: [
      { key: "/admin/users", label: "账号管理" },
      { key: "/admin/users/feedback", label: "用户报错反馈" },
    ],
  },
  { key: "/admin/profile", icon: <IdcardOutlined />, label: "管理员信息" },
];

/** 普通用户：datasheet 助理 / 问题反馈 / 用户信息 */
const USER_MENU = [
  { key: "/assistant", icon: <RobotOutlined />, label: "datasheet 助理" },
  { key: "/feedback", icon: <CommentOutlined />, label: "问题反馈" },
  { key: "/profile", icon: <UserOutlined />, label: "用户信息" },
];

/**
 * 当前角色该显示哪套菜单。
 * 传 role 而不是 user：以后加"访客"等角色时只改这里。
 */
export function menuFor(role) {
  return role === "admin" ? ADMIN_MENU : USER_MENU;
}
