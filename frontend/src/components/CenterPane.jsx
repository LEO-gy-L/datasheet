/**
 * 居中面板容器
 * ============
 * 把一个块摆在内容区的**正中央**（水平 + 垂直都居中），并且限制最大宽度。
 *
 * 为什么值得单独抽一个组件：
 *   「管理员信息」「用户信息」「修改密码」三个页面都要这个效果，
 *   如果各写各的，改一次留白要改三处，早晚会有一处长得不一样。
 *
 * ---------------------------------------------------------------------------
 * 两个细节决定它好不好用：
 *
 * ① 用 minHeight 而不是 height
 *    写 height: 100% 的话，内容一超过容器高度就会被"居中裁掉顶部"
 *    （居中布局的经典坑：溢出方向是两头，但滚动条只能往下滚）。
 *    minHeight 的语义是"至少占满一屏高，内容多了就自己变高"，
 *    于是内容少时居中、内容多时正常往下排 —— 两种情况都对。
 *
 * ② 用 grid + place-items 而不是 flex + margin:auto
 *    grid 这一行就同时管住水平垂直，不用再写 align/justify 两句。
 *
 * @param {number} width 面板最大宽度。表单类页面 440~560 最舒服 ——
 *                       再宽输入框会长得"拉不住"，阅读视线要来回扫。
 */
export default function CenterPane({ width = 520, children }) {
  return (
    <div style={{ minHeight: "100%", display: "grid", placeItems: "center" }}>
      <div style={{ width: "100%", maxWidth: width }}>{children}</div>
    </div>
  );
}
