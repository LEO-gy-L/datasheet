import { Menu } from "antd";
import { useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "@/context/AuthContext.jsx";
import { menuFor } from "@/menu.jsx";

/**
 * 「不在菜单里、但属于某个菜单项」的地址 -> 该高亮的菜单 key。
 *
 * 为什么需要这张表：
 *   侧栏高亮是靠"地址 == 菜单 key"精确匹配的。
 *   改密码页（/admin/password、/profile/password）**刻意不放进菜单**
 *   （菜单只留三个词条），地址在菜单里找不到对应项，
 *   结果就是点进去之后左边**一个高亮都没有** —— 用户会以为自己跳出了系统。
 *   有了这张表，改密码页仍然让「管理员信息 / 用户信息」亮着，
 *   位置感不断，也不用往菜单里塞第四个词条。
 */
const MENU_PARENT = {
  "/admin/password": "/admin/profile",
  "/profile/password": "/profile",
};

/**
 * 左侧菜单栏。
 *
 * 关键点只有两个：
 *   1. 菜单项从 menu.jsx 里按角色取 —— 管理员三个词条（含一个二级），用户三个词条
 *   2. key 就是路由路径，所以点击时直接 navigate(key)，不需要额外的映射表
 */
export default function Sidebar() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const isAdmin = user?.role === "admin";

  return (
    <Menu
      mode="inline"
      // 菜单数据：管理员 / 用户 两套
      items={menuFor(user?.role)}
      // 当前高亮哪一项。用完整 pathname 匹配 —— 因为 key 就是路径，
      // 连 /admin/users/feedback 这种三级地址也能精确对上。
      // 匹配不上时（比如改密码页）回退到它的"归属项"，见上面的 MENU_PARENT。
      selectedKeys={[MENU_PARENT[location.pathname] ?? location.pathname]}
      // 默认展开「用户管理」。只有管理员有二级菜单，所以只在管理员时给值。
      defaultOpenKeys={isAdmin ? ["grp-users"] : []}
      onClick={({ key }) => navigate(key)}
      style={{
        borderInlineEnd: "none", // 去掉 antd 自带的右边框，外层 Sider 已经有一条了
        background: "transparent",
        // 菜单离顶栏留 12px —— 刚好让它跟品牌区错开，
        // 太贴顶会显得"挤"，太大又像没做完
        paddingTop: 12,
      }}
    />
  );
}
