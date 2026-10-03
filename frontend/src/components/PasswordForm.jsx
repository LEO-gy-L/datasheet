import { App, Button, Card, Form, Input, Space, Typography } from "antd";
import { useState } from "react";

import { changePassword } from "@/api/auth.js";
import { safeValidate } from "@/utils/form.js";

const { Text } = Typography;

/**
 * 修改密码（管理员和普通用户共用的同一张卡）
 * ==========================================
 * 这个组件是"自给自足"的：自己持有表单实例、自己校验、自己提交、自己弹提示。
 * 外面（页面）不用传任何回调进来，只负责把它摆到页面上。
 *
 * 为什么不让父页面管提交：
 *   谁的数据谁负责。父页面如果只是"把它摆上去"，就没必要知道
 *   这里有几个字段、旧密码错了该提示什么。少一层传参，改起来就少一处漏。
 *
 * ---------------------------------------------------------------------------
 * 三个字段的作用，以及为什么必须一起提供：
 *   oldPassword   当前密码 —— 后端要拿它验证"你确实是本人"。只有登录态是不够的，
 *                 否则别人趁你电脑没锁屏就能把密码改掉。
 *   newPassword   新密码   —— 最低 6 位（跟后端校验保持一致）
 *   confirm       确认密码 —— 纯前端校验，防止手滑输错。故意输错两次，
 *                 下次登录就进不去了，这个成本比多填一个框高得多。
 *
 * confirm 的校验为什么写成函数（({ getFieldValue }) => ...）：
 *   它要**跨字段比较**，得先拿到 newPassword 的值。
 *   配置对象写法拿不到别的字段，只能换成这种"返回校验规则"的函数形式，
 *   并且在上面写 dependencies 声明依赖 —— 否则改了新密码，
 *   下面的确认框不会自动重新校验。
 */
export default function PasswordForm() {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  async function submit() {
    // 校验失败会返回 null（antd 已经把红字画在字段下面了），直接收工。
    // 为什么要这层包装：见 utils/form.js 开头 —— 直接 await validateFields()
    // 会让校验失败变成一条"未捕获的 promise 错误"打到控制台。
    const values = await safeValidate(form);
    if (!values) return;

    setSaving(true);
    try {
      await changePassword({
        oldPassword: values.oldPassword,
        newPassword: values.newPassword,
      });
      form.resetFields(); // 清空，免得密码留在输入框里
      message.success("密码已修改，下次登录请用新密码");
    } catch (err) {
      message.error(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card title="修改密码">
      {/* requiredMark={false}：表单的 * 号在"极简"风格里是噪点，
          提示语本来就会告诉用户必填，不必再加标记 */}
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item
          name="oldPassword"
          label="当前密码"
          rules={[{ required: true, message: "请输入当前密码" }]}
        >
          <Input.Password autoComplete="current-password" placeholder="验证身份用" />
        </Form.Item>

        <Form.Item
          name="newPassword"
          label="新密码"
          rules={[
            { required: true, message: "请输入新密码" },
            { min: 6, message: "至少 6 位" },
          ]}
        >
          <Input.Password autoComplete="new-password" placeholder="至少 6 位" />
        </Form.Item>

        <Form.Item
          name="confirm"
          label="确认新密码"
          // dependencies：告诉 antd 这个字段要跟着 newPassword 一起重新校验
          dependencies={["newPassword"]}
          rules={[
            { required: true, message: "请再输一次新密码" },
            ({ getFieldValue }) => ({
              validator(_, value) {
                // 空值交给上面那条 required 去报，这里只负责"两次是否一致"
                if (!value || getFieldValue("newPassword") === value) {
                  return Promise.resolve();
                }
                return Promise.reject(new Error("两次输入的密码不一致"));
              },
            }),
          ]}
        >
          <Input.Password autoComplete="new-password" placeholder="再输一次" />
        </Form.Item>

        <Space>
          <Button type="primary" loading={saving} onClick={submit}>
            保存
          </Button>
          <Text type="secondary" style={{ fontSize: 12 }}>
            改完下次登录用新密码
          </Text>
        </Space>
      </Form>
    </Card>
  );
}
