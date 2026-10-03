import { App, Button, Card, Descriptions, Form, Input, Tag, Typography } from "antd";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { updateProfile } from "@/api/auth.js";
import CenterPane from "@/components/CenterPane.jsx";
import { useAuth } from "@/context/AuthContext.jsx";
import { safeValidate } from "@/utils/form.js";

const { Text, Link } = Typography;

/**
 * 信息页（管理员 / 普通用户共用同一个页面组件）
 * ============================================
 * 这一页只干一件事：**改自己的显示名字和邮箱**。
 *
 * ---------------------------------------------------------------------------
 * 为什么两个角色共用一个组件（原来是 admin/Profile.jsx + user/Profile.jsx 两份）
 * ---------------------------------------------------------------------------
 * 合并前量过一次：两份文件"有意义代码行"的重复度是 **76%** ——
 * 除了「角色标签写什么」「改密码跳哪」以外完全一样。
 *
 * 原来我在注释里辩护说"两页属于不同角色分组，各自可能单独演进，故意不合并"。
 * 那个理由站不住：**要演进的是字段，而字段两边一模一样。**
 * 表现为 76% 重复的两个文件，真正的成本不是行数，是——
 *   以后加一个"手机号"字段，要记得改两处；漏一处就是"管理员能改、用户改不了"，
 *   而且这种 bug 只在特定角色下才复现，最难查。
 * 所以现在合成一份，角色差异用 isAdmin 就地算出来。
 *
 * 判断一个组件该不该抽，标准不是"长得像不像"，而是**会不会同步变化**。
 * 这两页会（字段一定一起加），所以该合。
 * 反例见 admin/Feedback.jsx 和 user/Feedback.jsx —— 那两份重复度只有 18%，
 * 一个是"管理员管答复的表格"，一个是"用户只读的列表"，不会同步变化，就不该合。
 *
 * ---------------------------------------------------------------------------
 * 为什么这一页只剩一张卡、且改密码搬去了独立一页
 * ---------------------------------------------------------------------------
 *   · 原来左栏"基本信息"、右栏"修改密码"并排。问题是两栏都只有几个输入框，
 *     并排之后每栏都很窄，页面重心还偏左，右边空一大片，看着像没做完。
 *   · 改密码是**低频且需要专注**的操作（要回忆旧密码、要输两遍新密码），
 *     跟"改个名字"这种随手操作混一屏容易手滑。拆开后两边都能居中、都能给足宽度。
 *
 * ---------------------------------------------------------------------------
 * 为什么底部入口只写"修改密码"，不写"忘记密码？"
 * ---------------------------------------------------------------------------
 * 这一页在路由守卫**之内**，只有已经登录的人才能进来 ——
 * 既然人都登进来了，"忘没忘密码"就不成立：真忘了密码的人连这里都到不了。
 * "忘记密码"是**登录页**的功能，而且必须先有后端（管理员重置 / 邮箱验证码）
 * 才有意义 —— 它要证明"你是本人"，而这件事前端做不到。
 */
export default function Profile() {
  const { user, updateProfile: syncProfile } = useAuth();
  const { message } = App.useApp();
  const navigate = useNavigate();

  const [infoForm] = Form.useForm();
  const [savingInfo, setSavingInfo] = useState(false);

  const isAdmin = user?.role === "admin";

  async function saveInfo() {
    const values = await safeValidate(infoForm);
    if (!values) return;
    setSavingInfo(true);
    try {
      await updateProfile(values);
      // 同步到全局登录态，否则右上角头像旁边还是旧名字
      syncProfile({ name: values.name, email: values.email });
      message.success("已保存");
    } catch (err) {
      message.error(err.message);
    } finally {
      setSavingInfo(false);
    }
  }

  return (
    <CenterPane width={520}>
      <Card title="基本信息">
        {/* 账号和角色不给改：账号是登录凭据，角色只用于权限判定，
            开放给页面随便改等于把权限系统架空了。

            账号用等宽字体（Text code）：型号 / 用户名这类"标识符"用等宽更专业，
            而且 l 和 1、O 和 0 不会看混。 */}
        <Descriptions column={1} size="small" style={{ marginBottom: 16 }}>
          <Descriptions.Item label="登录账号">
            <Text code>{user?.username}</Text>
          </Descriptions.Item>
          <Descriptions.Item label="角色">
            {isAdmin ? <Tag className="tag-solid">管理员</Tag> : <Tag>普通用户</Tag>}
          </Descriptions.Item>
        </Descriptions>

        <Form
          form={infoForm}
          layout="vertical"
          requiredMark={false}
          initialValues={{ name: user?.name, email: user?.email }}
        >
          <Form.Item name="name" label="显示名字" rules={[{ required: true, message: "名字不能为空" }]}>
            <Input placeholder="显示在右上角的名字" />
          </Form.Item>
          <Form.Item name="email" label="邮箱" rules={[{ type: "email", message: "邮箱格式不对" }]}>
            <Input placeholder="可选" />
          </Form.Item>
          <Button type="primary" loading={savingInfo} onClick={saveInfo}>
            保存
          </Button>
        </Form>

        {/* 改密码入口。用一条细线跟上面隔开 ——
            它跟"保存资料"是两件不同的事，混在没有分隔的同一片区域里
            会让人以为也是点上面那个"保存"来提交。

            链接为什么要显式加下划线：全站主色是近黑，跟正文几乎同一个颜色，
            不给下划线的话"这行字能不能点"完全看不出来。 */}
        <div
          style={{
            borderTop: "1px solid var(--line)",
            marginTop: 20,
            paddingTop: 14,
            fontSize: 13,
          }}
        >
          <Link
            onClick={() => navigate(isAdmin ? "/admin/password" : "/profile/password")}
            style={{ textDecoration: "underline", textUnderlineOffset: 3 }}
          >
            修改密码
          </Link>
        </div>
      </Card>
    </CenterPane>
  );
}
