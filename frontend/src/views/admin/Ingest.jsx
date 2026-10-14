import {
  DeleteOutlined,
  InboxOutlined,
  ReloadOutlined,
  SyncOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import { App, Button, Card, Progress, Space, Table, Tag, Tooltip, Typography, Upload } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";

import { deleteDocument, indexDocument, listDocuments, uploadDocument } from "@/api/docs.js";

const { Text } = Typography;

/**
 * 管理员 · 文档入库
 * ==================
 * 上传数据手册 -> 列表里多一行「未入库」-> 点「开始建库」才真的解析切块向量化。
 *
 * 为什么上传和建库要拆成两步（这个设计很重要，别合并）
 * -----------------------------------------------------
 *   上传 = 存文件，毫秒级；
 *   建库 = 解析 PDF + 切块 + 调智谱 embedding 向量化，
 *          慢（几十秒到十几分钟）而且**按 token 花钱**。
 *   合成一个按钮的话：用户点一下要转圈很久，中途断网就前功尽弃；
 *   而且传错了文件想删，钱已经花掉了。
 *   拆开之后：上传完可以先看列表、可以攒一批再统一入库、
 *   可以先删掉传错的文件 —— **在花钱之前**都有反悔的机会。
 *
 * 【2026-10-03 P5】后端接上之后的三个变化
 * ----------------------------------------
 *   ① 状态不再是"已入库/未入库"两态，而是四态：
 *      uploaded（未入库）/ indexing（建库中）/ indexed（已入库）/ failed（失败）
 *      为什么 failed 必须单独一态：建库失败往往是**确定性**原因
 *      （PDF 是扫描版没有文字层）。如果它显示成"未入库"，
 *      用户会再点一次建库、再失败一次 —— 反复花时间。
 *      单独的失败态 + 原因提示，才能把"再试一次有用"和"再试一次白搭"分开。
 *
 *   ② 建库是**异步**的：接口不到一秒就返回，真正的活儿在后端线程里跑。
 *      所以这里要做**轮询** —— 见下面那个 useEffect。
 *      不需要 WebSocket / SSE：建库是低频操作，几秒一次的轮询足够了，
 *      而且实现简单得多、断了也不会有状态残留。
 *
 *   ③ 上传只收 .pdf。原因是入库流水线（解析正文/表格/矢量图）整套都建立在
 *      pymupdf 上，收下 .txt 的后果不是"不支持"，而是"传成功了但建库失败"。
 *      宁可在上传这一步就说清楚。
 */

/** 把字节数变成人看的大小 */
function formatSize(bytes) {
  if (!bytes) return "-";
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

/** 轮询间隔（毫秒）。2.5 秒是个折中：
 *  再快一点（1 秒）就是在反复读一个几秒才变一次的数据库字段，纯浪费；
 *  再慢一点（10 秒）进度条会看起来一顿一顿的，像卡住了。 */
const POLL_MS = 2500;

/** 状态 -> 标签。抽成一张表而不是一长串 if/else：
 *  四个状态的样式一眼能看全，加状态时也不会漏掉某一处。 */
const STATUS_TAG = {
  uploaded: { color: "default", text: "未入库" },
  indexing: { color: "processing", text: "建库中" },
  indexed: { color: "success", text: "已入库" },
  failed: { color: "error", text: "建库失败" },
};

export default function Ingest() {
  const { message, modal } = App.useApp();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  // 已选中、还没点「上传」的文件
  const [pending, setPending] = useState([]);
  const [busy, setBusy] = useState(false);

  /**
   * 拉列表。
   *
   * `silent` 参数是给轮询用的：轮询如果也把 loading 置 true，
   * 表格每 2.5 秒会闪一次骨架屏 —— 看起来像在反复重载，
   * 非常难受。静默刷新只换数据、不动加载态。
   */
  const load = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      try {
        setRows(await listDocuments());
      } catch (err) {
        // 轮询失败**不弹提示**：网络抖一下弹一条红字太吵，
        // 而且下一个周期就会自己恢复。
        // 首次加载失败必须提示 —— 那是"页面打不开"，用户得知道原因。
        if (!silent) message.error(err.message);
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [message]
  );

  useEffect(() => {
    load();
  }, [load]);

  /* ---------------------------------------------------- 建库进度轮询
     ⚠️ 依赖数组里放的是 `hasIndexing`（一个布尔），不是 `rows`。
        放 rows 的话，每次轮询拿到新数组 -> effect 重跑 -> 清掉旧定时器
        再建一个新的，等于每次都在重置计时。虽然也能跑，但每次都在
        "拆了重建"，而且轮询间隔会从数据返回的那一刻重新算起，
        实际间隔变成"请求耗时 + 2.5 秒"，越跑越飘。
        放布尔值：只有"有没有在建库的"这件事**翻转**时才会重建定时器。 */
  const hasIndexing = rows.some((r) => r.status === "indexing");

  // 用 ref 存 load，让下面的 effect 不需要把 load 放进依赖
  // （load 依赖 message，message 的引用在 antd 里不保证稳定，
  //   放进去会导致 effect 被无谓地重建）
  const loadRef = useRef(load);
  useEffect(() => {
    loadRef.current = load;
  }, [load]);

  useEffect(() => {
    if (!hasIndexing) return undefined;
    const timer = setInterval(() => loadRef.current(true), POLL_MS);
    return () => clearInterval(timer);
  }, [hasIndexing]);

  /* ---------------------------------------------------- 上传 */
  async function handleUpload() {
    if (pending.length === 0) {
      message.warning("先点「选择文件」挑要入库的手册");
      return;
    }
    setBusy(true);
    const ok = [];
    const failed = [];

    // 逐个上传，一个失败不影响其他的。
    // 为什么不用 Promise.all 一起发：那样只要有一个失败，
    // 整批都拿不到结果，而且服务端会同时收到一串请求、
    // 同时往 datasheets/ 里写文件 —— 没必要，用户一次也就传几份。
    for (const file of pending) {
      try {
        ok.push(await uploadDocument(file));
      } catch (err) {
        failed.push(`${file.name}：${err.message}`);
      }
    }

    setPending([]);
    setBusy(false);
    await load(true);

    if (ok.length) message.success(`已上传 ${ok.length} 个文件，点「开始建库」才会真的入库`);
    if (failed.length) {
      // 用 modal 而不是 message：失败原因通常不止一句（重名 / 不是 PDF / 太大），
      // message 会自动消失，用户来不及看完。
      modal.error({
        title: `${failed.length} 个文件没传上去`,
        content: (
          <ul style={{ paddingLeft: 18, margin: "8px 0 0", fontSize: 13, lineHeight: 1.8 }}>
            {failed.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        ),
      });
    }
  }

  /* ---------------------------------------------------- 建库 */
  function handleIndex(row) {
    const again = row.status === "indexed" || row.status === "failed";
    modal.confirm({
      title: again ? `重新建库《${row.name}》？` : `开始为《${row.name}》建库？`,
      content: (
        <div style={{ fontSize: 13, lineHeight: 1.8 }}>
          <p style={{ margin: "0 0 6px" }}>
            会依次跑：① 解析正文 ② 解析表格 ③ 切块 ④ 向量化入库。
          </p>
          <p style={{ margin: 0, color: "var(--ink-soft)" }}>
            其中第 ④ 步要调用智谱 embedding 接口（按 token 计费），
            几十秒到十几分钟。<b>可以离开这个页面</b>，进度会自己更新。
          </p>
          {row.status === "indexed" && (
            <p style={{ margin: "6px 0 0", color: "var(--ink-soft)" }}>
              这份手册已经在库里了 —— 重新建库会<b>替换</b>它原来的片段。
              已入库的旧片段不会重复计费（向量复用了），只会对新的片段收费。
            </p>
          )}
        </div>
      ),
      okText: "开始建库",
      cancelText: "取消",
      async onOk() {
        try {
          await indexDocument(row.id);
          // 不在这里手动改本地状态，而是立刻拉一次真实数据 ——
          // 手改状态和后台的真实状态很容易对不上（比如后台秒失败了），
          // 拉一次才知道真相。
          await load(true);
          message.success("已开始建库，进度会自己更新");
        } catch (err) {
          message.error(err.message);
        }
      },
    });
  }

  /* ---------------------------------------------------- 删除 */
  function handleDelete(row) {
    modal.confirm({
      title: `删除《${row.name}》？`,
      content: (
        <div style={{ fontSize: 13, lineHeight: 1.8 }}>
          <p style={{ margin: "0 0 6px" }}>
            会删掉：原始 PDF、三道中间产物，以及它在向量库里的
            <b> {row.chunks || 0} 个片段</b>。
          </p>
          <p style={{ margin: 0, color: "var(--ink-soft)" }}>
            删完之后助理页就搜不到它了，且<b>不可恢复</b>（要重新上传 + 建库）。
          </p>
        </div>
      ),
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      async onOk() {
        try {
          const res = await deleteDocument(row.id);
          setRows((prev) => prev.filter((r) => r.id !== row.id));
          message.success(`已删除（同时从向量库摘掉 ${res.removedChunks ?? 0} 个片段）`);
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
      render: (name, row) => (
        <div>
          <Text strong style={{ fontFamily: "var(--mono)", fontSize: 13 }}>
            {name}
          </Text>
          {/* 建库中：在文件名下面挂一条进度条。
              为什么要显示"第几批"：向量化这一步动辄几分钟，
              只给一个百分比的话，用户会怀疑是不是卡在 60% 不动了。
              带上"12/48 批"就能看出它确实在往前走。 */}
          {row.status === "indexing" && (
            <div style={{ marginTop: 6, maxWidth: 280 }}>
              <Progress
                percent={row.progress || 0}
                size="small"
                status="active"
                strokeColor="#18181b"
                /* ⚠️ width:100% 不能省。
                   antd 的 .ant-progress 默认是 display:inline-block 且不设宽度 ——
                   不写宽度的话进度条会缩成很短一小截（只有"够放文字"那么宽），
                   在大表格里看着像个故障。 */
                style={{ width: "100%", marginBottom: 2 }}
              />
              {/* ⚠️ display:block 也不能省。
                  antd 的 <Text> 渲染出来是个 <span>（行内元素），
                  不改成块级的话它会**贴在进度条右边**，和那个百分比数字挤在一行 ——
                  我们想要的是"进度条一行、阶段说明一行"。
                  这类"明明换了行却还在同一行"的问题，八成就是元素是 inline。 */}
              <Text
                type="secondary"
                style={{ fontSize: 11.5, display: "block" }}
              >
                {row.stage || "建库中…"}
              </Text>
            </div>
          )}
        </div>
      ),
    },
    { title: "大小", dataIndex: "size", width: 100, render: formatSize },
    {
      title: "类型",
      dataIndex: "type",
      width: 76,
      render: (t) => <Tag>{t || "?"}</Tag>,
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 130,
      render: (status, row) => {
        const conf = STATUS_TAG[status] ?? STATUS_TAG.uploaded;
        const tag =
          status === "indexing" ? (
            <Tag color="processing" icon={<SyncOutlined spin />}>
              {conf.text}
            </Tag>
          ) : (
            <Tag color={conf.color}>{conf.text}</Tag>
          );

        // 失败时把原因挂上去。用 Tooltip 而不是直接在表格里展开 ——
        // 报错原文经常有几十行（带子进程的 stdout 尾巴），
        // 铺在表格里会把整张表撑得没法看。
        if (status === "failed" && row.error) {
          return (
            <Tooltip
              title={
                <pre
                  style={{
                    margin: 0,
                    fontSize: 11.5,
                    maxHeight: 260,
                    maxWidth: 480,
                    overflow: "auto",
                    whiteSpace: "pre-wrap",
                    fontFamily: "var(--mono)",
                  }}
                >
                  {row.error}
                </pre>
              }
            >
              <span style={{ cursor: "help" }}>{tag}</span>
            </Tooltip>
          );
        }
        return tag;
      },
    },
    {
      title: "页数 / 片段",
      dataIndex: "pages",
      width: 116,
      render: (pages, row) => (
        <span style={{ fontFamily: "var(--mono)", fontSize: 12.5 }}>
          {pages || 0} / {row.chunks || 0}
        </span>
      ),
    },
    { title: "上传时间", dataIndex: "createdAt", width: 150 },
    {
      title: "操作",
      width: 200,
      render: (_, row) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            icon={<ReloadOutlined />}
            // 正在建库时禁用：后端也会拒绝（409），
            // 但让按钮直接变灰比"点了才被告知不行"体验好。
            disabled={row.status === "indexing"}
            onClick={() => handleIndex(row)}
          >
            {row.status === "uploaded" ? "开始建库" : "重新建库"}
          </Button>
          <Button
            type="link"
            size="small"
            danger
            icon={<DeleteOutlined />}
            disabled={row.status === "indexing"}
            onClick={() => handleDelete(row)}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <Card
      title="文档入库"
      extra={
        <Space size={10}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            共 {rows.length} 条
            {hasIndexing && " · 有任务在建库中"}
          </Text>
          <Button size="small" icon={<ReloadOutlined />} onClick={() => load()}>
            刷新
          </Button>
        </Space>
      }
    >
      {/* 选择文件：beforeUpload 返回 false 表示"先别传"，只把文件收进 pending，
          真正的上传等点「上传文件」。 */}
      <Space style={{ marginBottom: 12 }} wrap>
        <Upload
          multiple
          showUploadList={false}
          beforeUpload={() => false}
          accept=".pdf"
          fileList={pending}
          onChange={({ fileList }) => setPending(fileList.map((f) => f.originFileObj ?? f))}
        >
          <Button icon={<UploadOutlined />}>选择文件</Button>
        </Upload>

        <Button type="primary" icon={<InboxOutlined />} loading={busy} onClick={handleUpload}>
          上传文件
        </Button>

        {pending.length > 0 && (
          <Text type="secondary" style={{ fontSize: 13 }}>
            已选 {pending.length} 个：{pending.map((f) => f.name).join("、")}
          </Text>
        )}
      </Space>

      <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 12 }}>
        只支持 .pdf。上传只是把文件存到服务器，还要点一次「开始建库」才会解析入库
        —— 因为建库要花钱（调用 embedding 接口），得给你留个反悔的机会。
        扫描版 PDF 抽不出文字层，建库会失败并给出原因。
      </Text>

      <Table
        rowKey="id"
        size="middle"
        columns={columns}
        dataSource={rows}
        loading={loading}
        pagination={{ pageSize: 8, showSizeChanger: false }}
      />
    </Card>
  );
}
