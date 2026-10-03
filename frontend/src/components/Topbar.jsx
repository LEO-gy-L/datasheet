import { useEffect, useState } from "react";

import { Badge, Tooltip } from "antd";

import { health } from "@/api/chat.js";
import AccountMenu from "@/components/AccountMenu.jsx";

/**
 * 顶栏：左边品牌，右边「后端状态 + 头像菜单」。
 *
 * 后端状态那个小圆点是每 10 秒探一次 /api/health。
 * 为什么值得做：这个项目前后端是两个进程，很容易出现"前端打开了、
 * 后端没启动"的情况。有个圆点，你一眼就知道该不该去点 start_backend.bat，
 * 而不是对着一个永远转圈的输入框猜。
 *
 * 排版上做了个"两级标题"的处理：
 *   主名 Datasheet（15px 中黑） + 副题 智能问答系统（12.5px 浅灰）
 * 比原来一行 16px 粗体**更像正经产品**，而且信息层次反而更清楚。
 */
export default function Topbar() {
  // null = 还在检测；true/false = 已连上 / 连不上
  const [online, setOnline] = useState(null);

  useEffect(() => {
    let alive = true;

    async function check() {
      try {
        await health();
        if (alive) setOnline(true);
      } catch {
        if (alive) setOnline(false);
      }
    }

    check();
    const timer = setInterval(check, 10000);

    // 清理：组件卸载后别再 setState（React 会警告内存泄漏）
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  const status = online === null ? "processing" : online ? "success" : "error";
  const text = online === null ? "检测后端…" : online ? "后端已连接" : "后端未启动";

  return (
    /* lineHeight: 1.6 不是装饰，是**必须写的纠错**：
       本组件渲染在 antd 的 <Header> 里，而 Header 自带一条 `line-height: 56px`
       （56 正好等于栏高 —— antd 是按"一行纯文字"设计的）。
       行高会被**继承**，于是任何有固定高度的子元素里都会凭空出现一个 56px 高的
       "行盒"，比元素本身还高，把里面的内容整个顶出去。
       下面的 logo 方块就是被这一条顶爆的（D 掉到方块外面）。
       这里把它重置回正常值，是从源头掐断污染 —— 而不是让每个子元素自己打补丁。 */
    <div
      style={{
        display: "flex",
        alignItems: "center",
        width: "100%",
        gap: 12,
        lineHeight: 1.6,
      }}
    >
      {/* 品牌区 */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, flex: 1, minWidth: 0 }}>
        {/* logo：纯黑圆角方块。原来那对紫蓝渐变跟"高级灰"冲突，去掉了。
            加了一层 inset 高光，让方块上沿有一条极淡的亮线 ——
            这是扁平色块看起来"有厚度"的小技巧。

            ↓ lineHeight: 1 是"让 D 留在方块里"的关键，必须写：

              方块内部的排版得由方块自己说了算。不写的话会继承外面的行高
              —— 上一层的 Header 是 56px，比这个 28px 的方块还高两倍，
              行高把行盒撑爆，字母就被顶到方块外面去了（D 掉到下方）。

              至于"为什么不再补一点 padding 让它绝对居中"：
              这个方块实测的垂直偏差是 0.13px（跟像素量出来的），
              已经远小于一个物理像素；再动 padding 反而会跨到下一个
              "取整台阶"上，直接偏 0.88px。所以这里**故意不加**。 */}
        <div
          style={{
            width: 28,
            height: 28,
            borderRadius: 8,
            background: "#18181B",
            boxShadow: "inset 0 1px 0 rgba(255,255,255,.14)",
            color: "#fff",
            display: "grid",
            placeItems: "center",
            fontSize: 14,
            fontWeight: 600,
            letterSpacing: 0,
            lineHeight: 1,
            flex: "0 0 28px",
          }}
        >
          D
        </div>

        <div style={{ display: "flex", alignItems: "baseline", gap: 8, minWidth: 0 }}>
          <span
            style={{
              fontSize: 15,
              fontWeight: 600,
              letterSpacing: -0.2,
              whiteSpace: "nowrap",
            }}
          >
            Datasheet
          </span>
          <span
            style={{
              fontSize: 12.5,
              color: "var(--ink-faint)",
              whiteSpace: "nowrap",
            }}
          >
            智能问答系统
          </span>
        </div>
      </div>

      {/* 后端状态 */}
      <Tooltip title={online === false ? "请先双击项目根目录的 start_backend.bat" : text}>
        <span style={{ whiteSpace: "nowrap" }}>
          <Badge
            status={status}
            text={<span style={{ fontSize: 12.5, color: "var(--ink-soft)" }}>{text}</span>}
          />
        </span>
      </Tooltip>

      {/* 一条竖直细线，把"状态"和"账号"隔开 —— 比留空更有秩序感 */}
      <span
        style={{
          width: 1,
          height: 18,
          background: "var(--line)",
          flex: "0 0 1px",
        }}
      />

      {/* 头像 + 下拉菜单 */}
      <AccountMenu />
    </div>
  );
}
