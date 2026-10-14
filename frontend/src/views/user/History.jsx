import {
  DeleteOutlined,
  DownOutlined,
  HistoryOutlined,
  RightOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import { App, Button, Card, Empty, Input, Popconfirm, Skeleton, Space, Tag, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";

import { clearHistory, deleteHistory, listHistory } from "@/api/history.js";
import { toHtml } from "@/utils/markdown.js";

const { Text } = Typography;

/**
 * 用户 · 历史问答
 * ================
 * 列出我提过的每一个问题，点一条展开看当时的完整回答（含出处页码）。
 *
 * 数据来源：qa_history 表 —— 用户每问一次，后端答完就顺手写一行（见 api/qa.py）。
 * 所以这个页面**天然是"我自己的"**：后端按 token 里的用户 id 过滤，
 * 前端连"查谁的"这个参数都不需要传（传了也没用）。
 *
 * ---------------------------------------------------------------------------
 * 三个界面上的决定，以及为什么
 * ---------------------------------------------------------------------------
 * ① **一次只展开一条**（手风琴），而不是每条都能独立展开
 *    答案通常是几屏长的表格和正文。允许多条同时展开的话，用户来回对比时
 *    要在很长的页面里滚动，很容易滚丢自己刚看的是哪条。
 *    一次一条，"当前在看哪一条"永远是明确的。
 *
 * ② 答案用 markdown 渲染（跟助理页同一套 utils/markdown.js）
 *    保证同一个答案在两处长得一模一样。顺带说明为什么必须走那个函数：
 *    里面有一层 DOMPurify，直接塞 innerHTML 是 XSS 漏洞。
 *
 * ③ 搜索做在**服务端**（交给后端 ilike 查），不是前端过滤
 *    现在历史条数少，前端过滤也能跑；但条数一多就必然要分页，
 *    分页之后前端手里只有当前这一页的数据，"在整段历史里搜"就实现不了。
 *    一开始就做对，比以后返工便宜。
 */
export default function History() {
  const { message } = App.useApp();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");

  // 当前展开的那一条的 id。null = 全都收起
  const [activeId, setActiveId] = useState(null);

  const load = useCallback(
    async (kw) => {
      setLoading(true);
      try {
        setRows(await listHistory({ keyword: kw }));
        // 重新加载后原本展开的那条可能已经不在列表里了（被搜掉了），直接收起
        setActiveId(null);
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

  /** 删一条。乐观更新的反面 —— 这里选择"等服务端确认后再改界面"：
   *  删除是不可逆操作，宁可让用户多等 200ms，也不要出现"界面删了但服务端没删"的假象。 */
  async function removeOne(id) {
    try {
      await deleteHistory(id);
      setRows((prev) => prev.filter((r) => r.id !== id));
      if (activeId === id) setActiveId(null);
      message.success("已删除");
    } catch (err) {
      message.error(err.message);
    }
  }

  async function removeAll() {
    try {
      const res = await clearHistory();
      setRows([]);
      setActiveId(null);
      message.success(`已清空 ${res.count} 条历史`);
    } catch (err) {
      message.error(err.message);
    }
  }

  return (
    <Card
      title="历史问答"
      extra={
        <Space size={8}>
          <Input.Search
            allowClear
            prefix={<SearchOutlined style={{ color: "var(--ink-faint)" }} />}
            placeholder="搜问过的内容"
            style={{ width: 220 }}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onSearch={(v) => load(v)}
          />
          {/* Popconfirm 而不是直接删：清空是不可逆的，必须问一句。
              按钮在没有数据时直接禁用，省得用户点了个没反应的东西。 */}
          <Popconfirm
            title="清空全部历史？"
            description="删除后无法恢复。"
            okText="清空"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={removeAll}
            disabled={rows.length === 0}
          >
            <Button danger size="middle" disabled={rows.length === 0}>
              清空
            </Button>
          </Popconfirm>
        </Space>
      }
    >
      <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 16 }}>
        这里只保存你自己的提问记录，其他人看不到。点一条可以展开当时的完整回答。
      </Text>

      {loading ? (
        <Skeleton active paragraph={{ rows: 6 }} />
      ) : rows.length === 0 ? (
        <Empty
          image={<HistoryOutlined style={{ fontSize: 40, color: "var(--ink-faint)" }} />}
          description={keyword ? "没有匹配的记录" : "还没有提问记录"}
        />
      ) : (
        rows.map((row) => (
          <HistoryItem
            key={row.id}
            row={row}
            open={activeId === row.id}
            onToggle={() => setActiveId((prev) => (prev === row.id ? null : row.id))}
            onDelete={() => removeOne(row.id)}
          />
        ))
      )}
    </Card>
  );
}

/** 单条历史 */
function HistoryItem({ row, open, onToggle, onDelete }) {
  return (
    <div
      className="hist-item"
      style={{
        background: open ? "var(--bg-surface)" : "var(--bg-page)",
        border: "1px solid var(--line)",
        borderRadius: 10,
        marginBottom: 10,
        overflow: "hidden",
      }}
    >
      {/* 头部整行可点（不只是那个小三角）——
          三角图标只有 12px，做成唯一点击目标的话，每次都要瞄准，很烦 */}
      <div
        onClick={onToggle}
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: 10,
          padding: "12px 14px",
          cursor: "pointer",
        }}
      >
        <span style={{ color: "var(--ink-faint)", fontSize: 12, marginTop: 3 }}>
          {open ? <DownOutlined /> : <RightOutlined />}
        </span>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 500 }}>{row.question}</div>

          <Space size={6} wrap style={{ marginTop: 6 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {row.createdAt}
            </Text>
            {/* 当时限定了哪份手册。没限定就不显示这个标签 ——
                显示一个"全部手册"的标签只会增加噪音 */}
            {row.sourceDoc && (
              <Tag style={{ fontFamily: "var(--mono)", fontSize: 11 }}>{row.sourceDoc}</Tag>
            )}
            {typeof row.seconds === "number" && row.seconds > 0 && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                耗时 {row.seconds}s
              </Text>
            )}
          </Space>
        </div>

        {/* 删除按钮在头部里，但要挡掉冒泡 ——
            否则点"删除"会先触发展开/收起，看起来像点歪了 */}
        <Popconfirm
          title="删除这条记录？"
          okText="删除"
          cancelText="取消"
          okButtonProps={{ danger: true }}
          onConfirm={onDelete}
        >
          <Button
            type="text"
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={(e) => e.stopPropagation()}
          />
        </Popconfirm>
      </div>

      {open && (
        <div
          style={{
            borderTop: "1px solid var(--line)",
            padding: "14px 14px 16px",
            background: "var(--bg-surface)",
          }}
        >
          {row.sources?.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 6 }}>
                答案出处
              </Text>
              <Space size={6} wrap>
                {row.sources.map((s, i) => (
                  <span key={i} className="src">
                    {s}
                  </span>
                ))}
              </Space>
            </div>
          )}

          {/* markdown 渲染。toHtml 内部过了一层 DOMPurify（防 XSS），
              不能图省事直接塞 innerHTML */}
          <div className="md" dangerouslySetInnerHTML={toHtml(row.answer)} />
        </div>
      )}
    </div>
  );
}
