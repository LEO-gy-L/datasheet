import { EditOutlined, KeyOutlined } from "@ant-design/icons";
import { App, Button, Card, Form, Input, Modal, Space, Switch, Table, Tag, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";

import { listUsers, resetPassword, setUserStatus, updateUser } from "@/api/users.js";
import { safeValidate } from "@/utils/form.js";

const { Text } = Typography;

/**
 * 管理员 · 用户管理 → 账号管理
 * =============================
 * 这里做的是**管理员对别人**的操作：改账号名、重置密码、禁用账号。
 * 跟普通用户在「用户信息」页改自己名字 / 密码不是一回事（那是 api/auth.js）。
 *
 * 两个弹窗都用同一个 Modal + 不同 Form 实例的模式：
 *   编辑资料（账号名 / 名字 / 邮箱）
 *   重置密码（只填新密码）
 */
export default function Users() {
  const { message } = App.useApp();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");

  // 编辑资料弹窗
  const [editing, setEditing] = useState(null); // null = 关闭；否则是要编辑的那行
  const [editForm] = Form.useForm();
  const [editSaving, setEditSaving] = useState(false);

  // 重置密码弹窗
  const [pwTarget, setPwTarget] = useState(null);
  const [pwForm] = Form.useForm();
  const [pwSaving, setPwSaving] = useState(false);

  const load = useCallback(
    async (kw) => {
      setLoading(true);
      try {
        setRows(await listUsers({ keyword: kw }));
      } catch (err) {
        message.error(err.message);
      } finally {
        setLoading(false);
      }
    },
    [message]
  );

  useEffect(() => {
    load("");
  }, [load]);

  function openEdit(row) {
    setEditing(row);
    // 注意：Form 已经挂载过了，必须先 setFieldsValue 再显示，
    // 否则弹窗里还是上一个人的数据
    editForm.setFieldsValue({ username: row.username, name: row.name, email: row.email });
  }

  async function saveEdit() {
    const values = await safeValidate(editForm);
    if (!values) return;
    setEditSaving(true);
    try {
      const next = await updateUser(editing.id, values);
      setRows((prev) => prev.map((r) => (r.id === next.id ? next : r)));
      setEditing(null);
      message.success("已保存");
    } catch (err) {
      message.error(err.message);
    } finally {
      setEditSaving(false);
    }
  }

  async function savePassword() {
    const values = await safeValidate(pwForm);
    if (!values) return;
    setPwSaving(true);
    try {
      await resetPassword(pwTarget.id, values.password);
      pwForm.resetFields();
      setPwTarget(null);
      message.success(`已重置「${pwTarget.name}」的密码`);
    } catch (err) {
      message.error(err.message);
    } finally {
      setPwSaving(false);
    }
  }

  async function toggleStatus(row, checked) {
    const next = checked ? "active" : "disabled";
    try {
      await setUserStatus(row.id, next);
      setRows((prev) => prev.map((r) => (r.id === row.id ? { ...r, status: next } : r)));
      message.success(checked ? "已启用" : "已禁用");
    } catch (err) {
      message.error(err.message);
    }
  }

  const columns = [
    {
      title: "账号",
      dataIndex: "username",
      width: 120,
      // 账号是"标识符"，用等宽字体（理由同入库页的文件名）
      render: (v) => (
        <Text strong style={{ fontFamily: "var(--mono)", fontSize: 13 }}>
          {v}
        </Text>
      ),
    },
    { title: "名字", dataIndex: "name", width: 120 },
    {
      title: "角色",
      dataIndex: "role",
      width: 100,
      // 角色不用颜色区分，用"实心 / 空心"区分（见 global.css 的 .tag-solid）
      render: (r) =>
        r === "admin" ? <Tag className="tag-solid">管理员</Tag> : <Tag>普通用户</Tag>,
    },
    { title: "邮箱", dataIndex: "email", ellipsis: true },
    { title: "创建时间", dataIndex: "createdAt", width: 116 },
    { title: "最后登录", dataIndex: "lastLogin", width: 156 },
    {
      title: "启用",
      dataIndex: "status",
      width: 80,
      render: (s, row) => (
        <Switch
          size="small"
          checked={s === "active"}
          onChange={(checked) => toggleStatus(row, checked)}
        />
      ),
    },
    {
      title: "操作",
      width: 190,
      render: (_, row) => (
        <Space size={4}>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>
            编辑
          </Button>
          <Button type="link" size="small" icon={<KeyOutlined />} onClick={() => setPwTarget(row)}>
            重置密码
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <Card
      title="账号管理"
      extra={
        <Input.Search
          allowClear
          placeholder="搜账号 / 名字 / 邮箱"
          style={{ width: 240 }}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onSearch={(v) => load(v)}
        />
      }
    >
      <Table
        rowKey="id"
        size="middle"
        columns={columns}
        dataSource={rows}
        loading={loading}
        scroll={{ x: 980 }}
        pagination={{ pageSize: 8, showSizeChanger: false }}
      />

      {/* 编辑资料 */}
      <Modal
        title="编辑账号"
        open={Boolean(editing)}
        onCancel={() => setEditing(null)}
        onOk={saveEdit}
        confirmLoading={editSaving}
        okText="保存"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={editForm} layout="vertical" style={{ marginTop: 12 }}>
          <Form.Item name="username" label="账号名" rules={[{ required: true, message: "账号名不能为空" }]}>
            <Input />
          </Form.Item>
          <Form.Item name="name" label="显示名字" rules={[{ required: true, message: "名字不能为空" }]}>
            <Input />
          </Form.Item>
          <Form.Item name="email" label="邮箱" rules={[{ type: "email", message: "邮箱格式不对" }]}>
            <Input />
          </Form.Item>
        </Form>
      </Modal>

      {/* 重置密码 */}
      <Modal
        title={pwTarget ? `重置「${pwTarget.name}」的密码` : "重置密码"}
        open={Boolean(pwTarget)}
        onCancel={() => {
          pwForm.resetFields();
          setPwTarget(null);
        }}
        onOk={savePassword}
        confirmLoading={pwSaving}
        okText="确认重置"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={pwForm} layout="vertical" style={{ marginTop: 12 }}>
          <Form.Item
            name="password"
            label="新密码"
            rules={[
              { required: true, message: "请输入新密码" },
              { min: 6, message: "至少 6 位" },
            ]}
          >
            <Input.Password placeholder="至少 6 位" />
          </Form.Item>
          <Text type="secondary" style={{ fontSize: 12 }}>
            重置后请线下告知该用户，系统不会自动通知。
          </Text>
        </Form>
      </Modal>
    </Card>
  );
}
