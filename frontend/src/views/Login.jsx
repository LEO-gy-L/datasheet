import { LockOutlined, UserOutlined } from "@ant-design/icons";
import { App, Button, Form, Input, Space } from "antd";
import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "@/context/AuthContext.jsx";
import { homePathFor } from "@/router/guard.jsx";

/**
 * 登录页。
 *
 * 演示账号（现在还没接后端，账号是写死的，见 src/mock/data.js）：
 *   管理员   admin / admin123
 *   普通用户 zhang / 123456
 * 页面上放了两个"一键填充"按钮，省得每次手敲。
 * 接后端之后这两个按钮可以直接删掉。
 *
 * ---------------------------------------------------------------------------
 * 视觉：极简高级灰
 * 改版前是"紫蓝渐变背景 + 彩色光晕 + 大阴影卡片"，改版后：
 *   · 背景    纯浅灰，上面铺一层**极淡的网格纹理**（纯 CSS 画的，不是图片）
 *             —— 一点点点阵让空背景不空，而且有"工程/图纸"的味道
 *   · 卡片    白底 + 1px 细边框，**不要阴影**。灰阶系统靠线分层，不靠影子
 *   · logo    纯黑圆角方块，带一条 inset 高光
 *   · 按钮    黑底白字（主题里 colorPrimary 已经是近黑，这里不用管）
 * ---------------------------------------------------------------------------
 */
const DEMO = [
  { label: "管理员", username: "admin", password: "admin123" },
  { label: "普通用户", username: "zhang", password: "123456" },
];

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { message } = App.useApp();

  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  // 被路由守卫拦下来时会把原地址放进 state.from，登录后优先回那里
  const from = location.state?.from;

  async function onFinish(values) {
    setLoading(true);
    try {
      const user = await login(values.username, values.password);
      message.success(`欢迎回来，${user.name}`);
      // 注意顺序：先看有没有"原本想去的页面"，没有就按角色回各自首页
      navigate(from || homePathFor(user.role), { replace: true });
    } catch (err) {
      message.error(err.message || "登录失败");
    } finally {
      setLoading(false);
    }
  }

  function fill(demo) {
    form.setFieldsValue({ username: demo.username, password: demo.password });
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        background: "var(--bg-page)",
        padding: 24,
        position: "relative",
      }}
    >
      {/* 极淡网格纹理。为什么用 CSS 渐变而不是背景图：
          不用发一个图片请求，而且改网格大小只要动一个数字。
          透明度压到 .028 —— 只是在余光里有一点点结构，不抢主体。 */}
      <div
        className="login-grid"
        aria-hidden
        style={{
          position: "absolute",
          inset: 0,
          pointerEvents: "none",
          backgroundImage:
            "linear-gradient(rgba(9,9,11,.028) 1px, transparent 1px)," +
            "linear-gradient(90deg, rgba(9,9,11,.028) 1px, transparent 1px)",
          backgroundSize: "28px 28px",
        }}
      />

      <div style={{ width: 380, position: "relative" }}>
        {/* ---------------- 品牌区 ---------------- */}
        <div style={{ textAlign: "center", marginBottom: 26 }}>
          {/* logo 方块。里面那两个属性的来龙去脉，跟 Topbar.jsx 的 logo 一致
              （核心是 lineHeight: 1 —— 防止继承外面的大行高把行盒撑爆），
              区别只在补偿量：

              这个方块是 44px / 字号 20px。实测（逐像素扫描）要让字母 D
              视觉正中，需要往上补 1 ~ 2.75px 都行，取中间值 0.1em = 2px，
              左右都留着余量。换字号时它会自动跟着缩放，但**补完要重新扫一遍**
              —— 偏差是阶梯状量化的，不是连续变化的，见 workspace/tune-logo.mjs。 */}
          <div
            style={{
              width: 44,
              height: 44,
              borderRadius: 12,
              background: "#18181B",
              boxShadow: "inset 0 1px 0 rgba(255,255,255,.14)",
              color: "#fff",
              display: "grid",
              placeItems: "center",
              fontSize: 20,
              fontWeight: 600,
              lineHeight: 1,
              paddingBottom: "0.1em",
              margin: "0 auto 14px",
            }}
          >
            D
          </div>
          <div style={{ fontSize: 19, fontWeight: 600, letterSpacing: -0.3 }}>
            Datasheet 智能问答
          </div>
          <div style={{ fontSize: 13, color: "var(--ink-faint)", marginTop: 7 }}>
            芯片数据手册 · 检索增强问答平台
          </div>
        </div>

        {/* ---------------- 表单卡片 ---------------- */}
        <div
          style={{
            background: "var(--bg-surface)",
            border: "1px solid var(--line)",
            borderRadius: 14,
            padding: "26px 26px 22px",
          }}
        >
          <Form form={form} layout="vertical" onFinish={onFinish} requiredMark={false} size="large">
            <Form.Item name="username" rules={[{ required: true, message: "请输入账号" }]}>
              <Input
                prefix={<UserOutlined style={{ color: "var(--ink-faint)" }} />}
                placeholder="账号"
                autoComplete="username"
              />
            </Form.Item>

            <Form.Item
              name="password"
              rules={[{ required: true, message: "请输入密码" }]}
              style={{ marginBottom: 18 }}
            >
              <Input.Password
                prefix={<LockOutlined style={{ color: "var(--ink-faint)" }} />}
                placeholder="密码"
                autoComplete="current-password"
                onPressEnter={() => form.submit()}
              />
            </Form.Item>

            <Form.Item style={{ marginBottom: 0 }}>
              <Button
                type="primary"
                htmlType="submit"
                block
                loading={loading}
                style={{ height: 42, fontWeight: 500 }}
              >
                登录
              </Button>
            </Form.Item>
          </Form>

          {/* 演示账号：一条细线分隔，语气放低（11.5px 浅灰），
              不跟主表单抢注意力 */}
          <div
            style={{
              borderTop: "1px solid var(--line)",
              marginTop: 20,
              paddingTop: 15,
              textAlign: "center",
            }}
          >
            <div
              style={{
                fontSize: 11.5,
                color: "var(--ink-faint)",
                letterSpacing: 0.3,
                marginBottom: 10,
              }}
            >
              演示账号（尚未接后端，账号写死在前端）
            </div>
            <Space size={8}>
              {DEMO.map((d) => (
                <Button key={d.username} size="small" onClick={() => fill(d)}>
                  {d.label}
                </Button>
              ))}
            </Space>
          </div>
        </div>

        {/* ---------------- 页脚 ---------------- */}
        <div
          style={{
            textAlign: "center",
            marginTop: 18,
            fontSize: 11.5,
            color: "var(--ink-faint)",
            letterSpacing: 0.4,
          }}
        >
          LangChain · FAISS · DeepSeek
        </div>
      </div>
    </div>
  );
}
