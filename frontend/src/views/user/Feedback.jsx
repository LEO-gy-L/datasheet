import { CommentOutlined } from "@ant-design/icons";
import { Card, Empty, Segmented, Skeleton, Space, Tag, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";

import { FEEDBACK_STATUS, listFeedbacks } from "@/api/feedback.js";
import { useAuth } from "@/context/AuthContext.jsx";

const { Paragraph, Text } = Typography;

/**
 * 用户 · 问题反馈
 * ==============
 * 这个页面**只能看，不能新建**（按你的要求）——
 * 新的反馈要去「datasheet 助理」页，在具体那条回答下面点「反馈」按钮，
 * 这样反馈天然带着上下文（哪一轮问答让你不满意）。
 *
 * 页面做的事：把我提交过的反馈列出来，标清状态，如果管理员回了话就展示出来。
 *
 * 为什么没用 antd 的 List 组件：
 *   antd v6 已经把 List 标记为废弃（控制台会报 "please use Listy instead"）。
 *   与其跟着换一个还不稳定的新组件，不如直接 map 渲染 ——
 *   反正这里的每条卡片样式本来就全是自定义的，用 List 只是多套一层壳。
 */
export default function Feedback() {
  const { user } = useAuth();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await listFeedbacks({ username: user?.username }));
    } finally {
      setLoading(false);
    }
  }, [user?.username]);

  useEffect(() => {
    load();
  }, [load]);

  const shown = filter === "all" ? rows : rows.filter((r) => r.status === filter);
  const pendingCount = rows.filter((r) => r.status !== "resolved").length;

  return (
    <Card
      title={
        <Space>
          <span>问题反馈</span>
          {pendingCount > 0 && <Tag>{pendingCount} 条处理中</Tag>}
        </Space>
      }
      extra={
        <Segmented
          value={filter}
          onChange={setFilter}
          options={[
            { label: `全部 ${rows.length}`, value: "all" },
            { label: "待处理", value: "pending" },
            { label: "处理中", value: "processing" },
            { label: "已处理", value: "resolved" },
          ]}
        />
      }
    >
      <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 16 }}>
        提交新反馈请去「datasheet 助理」，在具体那条回答下面点「反馈」按钮。
      </Text>

      {loading ? (
        <Skeleton active paragraph={{ rows: 5 }} />
      ) : shown.length === 0 ? (
        <Empty
          image={<CommentOutlined style={{ fontSize: 40, color: "var(--ink-faint)" }} />}
          description="还没有反馈记录"
        />
      ) : (
        shown.map((row) => <FeedbackItem key={row.id} row={row} />)
      )}
    </Card>
  );
}

/** 单条反馈卡片 */
function FeedbackItem({ row }) {
  const resolved = row.status === "resolved";

  return (
    <div
      style={{
        background: "var(--bg-page)",
        borderRadius: 10,
        padding: "14px 16px",
        marginBottom: 12,
        border: "1px solid var(--line)",
      }}
    >
      <Space size={8} style={{ marginBottom: 10 }} wrap>
        <Tag color={FEEDBACK_STATUS[row.status]?.color}>
          {FEEDBACK_STATUS[row.status]?.label ?? row.status}
        </Tag>
        <Tag>{row.category}</Tag>
        <Text type="secondary" style={{ fontSize: 12 }}>
          提交于 {row.createdAt}
        </Text>
      </Space>

      <div style={{ marginBottom: 8 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          针对的问题
        </Text>
        <Paragraph style={{ margin: "2px 0 0", fontSize: 13 }}>{row.question}</Paragraph>
      </div>

      <div style={{ marginBottom: 8 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          我的反馈
        </Text>
        <Paragraph style={{ margin: "2px 0 0", fontSize: 13 }}>{row.content}</Paragraph>
      </div>

      {resolved ? (
        <div
          style={{
            background: "var(--bg-subtle)",
            border: "1px solid var(--line)",
            // 深一点的左竖线 = "这是给你的一条回复"，不需要绿色也能看出来
            borderLeft: "2px solid var(--ink-soft)",
            borderRadius: 6,
            padding: 10,
          }}
        >
          <Text style={{ fontSize: 12, color: "var(--ink)", fontWeight: 500 }}>
            管理员回复 · {row.repliedAt}
          </Text>
          <Paragraph style={{ margin: "2px 0 0", fontSize: 13, whiteSpace: "pre-wrap" }}>
            {row.reply || "（已处理，无附加说明）"}
          </Paragraph>
        </div>
      ) : (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {row.status === "processing" ? "管理员已查看，正在处理中…" : "还没被查看，请耐心等待。"}
        </Text>
      )}
    </div>
  );
}
