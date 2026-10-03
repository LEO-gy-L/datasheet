import {
  DeleteOutlined,
  InboxOutlined,
  ReloadOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import { App, Button, Card, Popover, Space, Table, Tag, Typography, Upload } from "antd";
import { useCallback, useEffect, useState } from "react";

import { deleteDocument, indexDocument, listDocuments, uploadDocument } from "@/api/docs.js";

const { Text, Title } = Typography;

/**
 * 管理员 · 入库（文档管理）
 * =========================
 * 上传数据手册 -> 列表里多一行「未入库」-> 点"重新入库"才真的解析切块建库。
 *
 * 为什么上传和建库要拆成两步（很重要，别合并）：
 *   上传 = 存文件，秒级；
 *   建库 = 解析 PDF + 切块 + 调智谱 embedding 向量化，慢（几十秒到几分钟）而且按 token 收费。
 *   合成一个按钮的话，用户点一下就卡在那里转圈，还会因为超时失败后白白花掉 token。
 *   拆开之后：上传完可以攒一批再统一入库，也可以先删掉传错的文件，不会浪费钱。
 */

/** 把字节数变成人看的大小 */
function formatSize(bytes) {
  if (!bytes) return "-";
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

export default function Ingest() {
  const { message, modal } = App.useApp();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  // 已选中、还没点"上传并入库"的文件
  const [pending, setPending] = useState([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await listDocuments());
    } catch (err) {
      message.error(err.message);
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleUpload() {
    if (pending.length === 0) {
      message.warning("先点「选择文件」挑要入库的手册");
      return;
    }
    setBusy(true);
    try {
      const added = [];
      // 逐个上传：失败一个不影响前面成功的（跟后端脚本里的入库策略一致）
      for (const file of pending) {
        added.push(await uploadDocument(file));
      }
      setRows((prev) => [...added, ...prev]);
      setPending([]);
      message.success(`已上传 ${added.length} 个文件，点「重新入库」开始建库`);
    } catch (err) {
      message.error(err.message);
    } finally {
      setBusy(false);
    }
  }

  function handleIndex(row) {
    modal.confirm({
      title: `确认对《${row.name}》建库？`,
      content: "解析 + 切块 + 向量化需要调用智谱 embedding 接口（按 token 计费），耗时几十秒。",
      okText: "开始建库",
      cancelText: "取消",
      async onOk() {
        try {
          await indexDocument(row.id);
          setRows((prev) =>
            prev.map((r) => (r.id === row.id ? { ...r, indexed: true } : r))
          );
          message.success("已提交建库（真实建库要等后端接上后才会真的跑）");
        } catch (err) {
          message.error(err.message);
        }
      },
    });
  }

  function handleDelete(row) {
    modal.confirm({
      title: `删除《${row.name}》？`,
      content: "会同时从向量库里移除它贡献的块。",
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      async onOk() {
        try {
          await deleteDocument(row.id);
          setRows((prev) => prev.filter((r) => r.id !== row.id));
          message.success("已删除");
        } catch (err) {
          message.error(err.message);
        }
      },
    });
  }

  const columns = [
    {
      title: "文件名",
      dataIndex: "name",
      ellipsis: true,
      // 文件名用等宽字体：CH32F103_Datasheet_CN.pdf 这种"下划线 + 数字"的名字，
      // 等宽下 l/1、O/0 不会看混，也更有技术系统的味道
      render: (name) => (
        <Text strong style={{ fontFamily: "var(--mono)", fontSize: 13 }}>
          {name}
        </Text>
      ),
    },
    { title: "大小", dataIndex: "size", width: 100, render: formatSize },
    {
      title: "类型",
      dataIndex: "type",
      width: 80,
      render: (t) => <Tag>{t || "?"}</Tag>,
    },
    {
      title: "已入库",
      dataIndex: "indexed",
      width: 96,
      render: (v, row) =>
        v ? (
          // 入库成功的话，把页数 / 块数放进 Popover，不占表格宽度
          <Popover
            content={
              <span style={{ fontSize: 12 }}>
                {row.pages} 页 · {row.chunks} 个块
              </span>
            }
          >
            <Tag color="success" style={{ cursor: "help" }}>
              是
            </Tag>
          </Popover>
        ) : (
          <Tag>否</Tag>
        ),
    },
    { title: "创建时间", dataIndex: "createdAt", width: 168 },
    {
      title: "操作",
      width: 210,
      render: (_, row) => (
        <Space size={4}>
          <Button type="link" size="small" disabled={!row.indexed}>
            预览
          </Button>
          <Button
            type="link"
            size="small"
            icon={<ReloadOutlined />}
            onClick={() => handleIndex(row)}
          >
            重新入库
          </Button>
          <Button type="link" size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(row)}>
            删除
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <Card
      title="文档管理"
      extra={
        <Text type="secondary" style={{ fontSize: 12 }}>
          共 {rows.length} 条
        </Text>
      }
    >
      {/* 选择文件：beforeUpload 返回 false 表示"先别传"，只把文件收进 pending，
          真正的上传等点「上传并入库」。 */}
      <Space style={{ marginBottom: 16 }} wrap>
        <Upload
          multiple
          showUploadList={false}
          beforeUpload={() => false}
          accept=".pdf,.txt,.md,.docx"
          fileList={pending}
          onChange={({ fileList }) => setPending(fileList.map((f) => f.originFileObj ?? f))}
        >
          <Button icon={<UploadOutlined />}>选择文件</Button>
        </Upload>

        <Button type="primary" icon={<InboxOutlined />} loading={busy} onClick={handleUpload}>
          上传并入库
        </Button>

        {pending.length > 0 && (
          <Text type="secondary" style={{ fontSize: 13 }}>
            已选 {pending.length} 个：{pending.map((f) => f.name).join("、")}
          </Text>
        )}
      </Space>

      <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 12 }}>
        支持 .pdf / .txt / .md / .docx。扫描版 PDF 可能抽不出文字层，需要先做 OCR。
      </Text>

      <Table
        rowKey="id"
        size="middle"
        columns={columns}
        dataSource={rows}
        loading={loading}
        pagination={{ pageSize: 5, showSizeChanger: false }}
      />
    </Card>
  );
}
