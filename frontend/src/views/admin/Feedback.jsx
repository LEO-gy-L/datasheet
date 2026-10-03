import { App, Button, Card, Drawer, Empty, Input, Segmented, Space, Table, Tag, Typography } from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";

import { FEEDBACK_STATUS, listFeedbacks, replyFeedback } from "@/api/feedback.js";

const { Paragraph, Text, Title } = Typography;

/**
 * 管理员 · 用户管理 → 用户报错反馈
 * ================================
 * 用户从「datasheet 助理」页某条回答下面点反馈提交，就落到这里。
 *
 * 表格只放摘要（谁、什么问题、状态），完整内容 + 回复在右侧抽屉里 ——
 * 因为"用户当时的提问 + 系统的回答 + 他的抱怨"这三段加起来很长，
 * 塞进表格会把行撑爆，也没法舒服地写回复。
 */
export default function Feedback() {
  const { message } = App.useApp();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState("all");

  const [current, setCurrent] = useState(null); // 抽屉里正在看的那条
  const [reply, setReply] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(
    async (st) => {
      setLoading(true);
      try {
        setRows(await listFeedbacks({ status: st === "all" ? undefined : st }));
      } catch (err) {
        message.error(err.message);
      } finally {
        setLoading(false);
      }
    },
    [message]
  );

  useEffect(() => {
    load(status);
  }, [load, status]);

  function openDetail(row) {
    setCurrent(row);
    setReply(row.reply ?? "");
  }

  /** 保存回复。传了 status 就一起改状态 */
  async function save(nextStatus) {
    setSaving(true);
    try {
      const updated = await replyFeedback(current.id, { status: nextStatus, reply });
      setCurrent(updated);
      setRows((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
      message.success(nextStatus === "resolved" ? "已回复并标记为已处理" : "已保存");
    } catch (err) {
      message.error(err.message);
    } finally {
      setSaving(false);
    }
  }

  // 各状态的数量，显示在筛选按钮上
  const counts = useMemo(() => {
    const c = { all: rows.length, pending: 0, processing: 0, resolved: 0 };
    for (const r of rows) c[r.status] = (c[r.status] ?? 0) + 1;
    return c;
  }, [rows]);

  const columns = [
    { title: "用户", dataIndex: "username", width: 100, render: (v) => <Text strong>{v}</Text> },
    {
      title: "分类",
      dataIndex: "category",
      width: 110,
      render: (v) => <Tag>{v}</Tag>,
    },
    { title: "针对的问题", dataIndex: "question", ellipsis: true },
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      render: (s) => (
        <Tag color={FEEDBACK_STATUS[s]?.color}>{FEEDBACK_STATUS[s]?.label ?? s}</Tag>
      ),
    },
    { title: "提交时间", dataIndex: "createdAt", width: 150 },
    {
      title: "操作",
      width: 90,
      render: (_, row) => (
        <Button type="link" size="small" onClick={() => openDetail(row)}>
          查看 / 回复
        </Button>
      ),
    },
  ];

  return (
    <Card
      title="用户报错反馈"
      extra={
        <Segmented
          value={status}
          onChange={setStatus}
          options={[
            { label: `全部 ${counts.all}`, value: "all" },
            { label: `待处理 ${counts.pending}`, value: "pending" },
            { label: `处理中 ${counts.processing}`, value: "processing" },
            { label: `已处理 ${counts.resolved}`, value: "resolved" },
          ]}
        />
      }
    >
      <Table
        rowKey="id"
        size="middle"
        columns={columns}
        dataSource={rows}
        loading={loading}
        scroll={{ x: 820 }}
        pagination={{ pageSize: 8, showSizeChanger: false }}
      />

      <Drawer
        size={560}
        open={Boolean(current)}
        onClose={() => setCurrent(null)}
        title="反馈详情"
        extra={
          current && (
            <Tag color={FEEDBACK_STATUS[current.status]?.color}>
              {FEEDBACK_STATUS[current.status]?.label}
            </Tag>
          )
        }
      >
        {!current ? (
          <Empty />
        ) : (
          <Space orientation="vertical" size={18} style={{ width: "100%" }}>
            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>
                提交人 · 时间 · 分类
              </Text>
              <div style={{ marginTop: 4 }}>
                <Text strong>{current.username}</Text>
                <Text type="secondary"> · {current.createdAt} · </Text>
                <Tag>{current.category}</Tag>
              </div>
            </div>

            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>
                用户当时问的
              </Text>
              <Paragraph style={{ margin: "4px 0 0" }}>{current.question}</Paragraph>
            </div>

            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>
                系统当时的回答
              </Text>
              <Paragraph
                style={{
                  margin: "4px 0 0",
                  background: "var(--bg-subtle)",
                  // 灰阶里没有颜色可用，就用左边这条竖线分层次：
                  // 浅灰线 = 系统回答（背景信息），深灰线 = 用户反馈（要点）
                  borderLeft: "2px solid var(--line)",
                  padding: 10,
                  borderRadius: 6,
                  whiteSpace: "pre-wrap",
                }}
              >
                {current.answer || "（空）"}
              </Paragraph>
            </div>

            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>
                用户的反馈内容
              </Text>
              <Paragraph
                style={{
                  margin: "4px 0 0",
                  background: "var(--bg-subtle)",
                  borderLeft: "2px solid var(--ink-soft)",
                  padding: 10,
                  borderRadius: 6,
                  whiteSpace: "pre-wrap",
                }}
              >
                {current.content}
              </Paragraph>
            </div>

            <div>
              <Title level={5} style={{ marginTop: 0 }}>
                回复用户
              </Title>
              <Input.TextArea
                rows={4}
                value={reply}
                onChange={(e) => setReply(e.target.value)}
                placeholder="说明处理结果，用户在「问题反馈」页能看到"
              />
              <Space style={{ marginTop: 12 }}>
                <Button loading={saving} onClick={() => save("processing")}>
                  仅保存（标记处理中）
                </Button>
                <Button type="primary" loading={saving} onClick={() => save("resolved")}>
                  回复并标记已处理
                </Button>
              </Space>
            </div>

            {current.repliedAt && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                上次处理时间：{current.repliedAt}
              </Text>
            )}
          </Space>
        )}
      </Drawer>
    </Card>
  );
}
