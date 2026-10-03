import { ArrowLeftOutlined } from "@ant-design/icons";
import { Button } from "antd";
import { useNavigate } from "react-router-dom";

import CenterPane from "@/components/CenterPane.jsx";
import PasswordForm from "@/components/PasswordForm.jsx";
import { useAuth } from "@/context/AuthContext.jsx";

/**
 * 修改密码页（管理员 / 普通用户共用同一个页面组件）
 * ================================================
 * 它原来只是「信息页」右边的半张卡片，现在独立成一页 ——
 * 好处是卡片能**摆到正中间**、有完整的宽度，不再跟"基本信息"挤成两栏。
 *
 * 为什么一个组件服务两种角色：
 *   两边除了"返回哪里"以外**没有任何区别**。为了这一个字符串去复制一个文件，
 *   以后改字段就要记住改两处 —— 那是纯粹的负债。
 *   路径按当前登录者的角色算出来即可。
 *
 * 两个路由都指向它（见 App.jsx）：
 *   /admin/password   管理员
 *   /profile/password 普通用户
 */
export default function ChangePassword() {
  const { user } = useAuth();
  const navigate = useNavigate();

  const isAdmin = user?.role === "admin";
  const back = isAdmin ? "/admin/profile" : "/profile";
  const backLabel = isAdmin ? "管理员信息" : "用户信息";

  return (
    <CenterPane width={440}>
      {/* position: relative 是给下面那个返回按钮当"定位参照物"用的 */}
      <div style={{ position: "relative" }}>
        {/* 返回入口。为什么用 absolute 浮在卡片外面，而不是跟着一起排：
              它一旦参与正常排版，CenterPane 居中的就是「按钮 + 卡片」这一整块，
              卡片就被按钮的高度顶下去了 —— 量出来正好偏 22px。
              改成绝对定位后，居中算的还是卡片本身，按钮贴在卡片上沿外侧，
              两件事互不干扰。

            bottom: 100% = 把按钮的底边贴到卡片顶边，再 marginBottom 退开 10px。
            为什么不用面包屑：只有一层，面包屑是"多此一举的仪式感"；
            一个带箭头的文字按钮更轻，也更符合"这就是个次级页面"的定位。

            paddingLeft 归零是为了让按钮文字跟卡片的左边缘**对齐** ——
            默认内边距会让它缩进去几像素，看着像没对齐。 */}
        <Button
          type="text"
          icon={<ArrowLeftOutlined />}
          onClick={() => navigate(back)}
          style={{
            position: "absolute",
            left: 0,
            bottom: "100%",
            marginBottom: 10,
            paddingLeft: 0,
            color: "var(--ink-soft)",
          }}
        >
          返回{backLabel}
        </Button>

        <PasswordForm />
      </div>
    </CenterPane>
  );
}
