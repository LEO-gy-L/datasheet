import { animate, stagger } from "animejs";

/* ============================================================================
   chatAnimation.js —— datasheet 助理页动效
   ============================================================================
   这份文件最初是从旧版 frontend/js/animation.js 移植过来的，
   后来**入场动画整体改写过一次**（用户反馈"跳跳的，看着想笑"），
   下面是改动的记录，免得以后有人照着旧印象去改：

   旧版入场 = 六段串成的时间轴（顶栏 → 标题 → 副标题 → 标签 → 卡片 → 建议问题），
   每段位移幅度还不一样（10 / 14 / 24 / 26px），卡片还带 scale 0.985→1。
   观感是"一个接一个从下面窜上来"，一跳一跳的。

   现在 = **整片一次滑入**：位移全部统一 12px、时长拉到 1s、缓动换 outCubic，
   只在元素之间留 40ms 的次序感。没有任何缩放，也没有回弹。

   ★ 还有一条硬伤是顺手修掉的（这才是"跳"最明显的原因）：
     `.chip` 在 `.card` 里面，旧代码让**父子两层同时位移**。
     CSS transform 是叠加的，卡片抬 26px 时，卡片里的 chip 还被自己再抬 10px，
     实际从 36px 外窜上来 —— 位移越叠越大，看起来就是"蹦"。
     所以现在只选 root 的**直接子元素**（`:scope > *`），父子绝不重复。

   另一个保留的约定：所有选择器都从传入的 root 往下找，不用全局选择器 ——
   助理页只是后台里的一页，全局的 `.card` 会命中 antd 所有 Card、`h1` 会命中每个标题。

   兜底照旧：anime.js 没加载成功时 HAS_ANIME 为 false，各函数直接 return。
   页面变朴素，但问答功能照常 —— 不让"动画库挂了"变成"页面不能用"。
   ============================================================================ */

const HAS_ANIME = typeof animate !== "undefined";

/**
 * 页面入场：整片平滑滑入。
 *
 * @param {HTMLElement|null} root 页面根节点
 */
export function animateIntro(root) {
  if (!HAS_ANIME || !root) return;

  // :scope > * 取 root 的所有**直接子元素**（标题 / 副标题 / 标签组 / 卡片 / 底部提示）。
  // 用这条选择器的两个理由：
  //   ① 新增内容块会自动跟上，不用回来改这个函数
  //   ② 它天然排除了"孙辈"，从根上避免父子 transform 叠加（见文件头说明）
  const els = root.querySelectorAll(":scope > *");
  if (!els.length) return;

  animate(els, {
    opacity: [0, 1],
    translateY: [12, 0],   // 所有元素位移完全一致 —— 整片掠过，不是各跳各的
    duration: 950,         // 拉到接近 1 秒：慢，才有"滑"的观感；快一定像"弹"
    delay: stagger(40),    // 只留 40ms 的次序感，几乎是同时出发
    // 缓动是"滑不滑"的关键，这里换过一次，记一下原因：
    //   outCubic  = 第一帧就以 3 倍平均速度冲出，末尾 200ms 又几乎不动
    //               —— 读起来是"窜出去然后刹车"，正是用户说的"呆/跳"。
    //   inOutSine = 起手慢慢加速、收尾慢慢减速，最高速度只有平均的 1.57 倍，
    //               全程像被"推"进去的，这才是"滑入"。
    // 代价是开头约 100ms 几乎不动（速度从 0 起来）——比起"啪一下窜出来"，这点等待值得。
    ease: "inOutSine",
  });
}

/**
 * 单条消息淡入上浮。
 *
 * 缓动和幅度都收了一档（原来 16px + outQuart 会有点"弹"）——
 * 消息是自己刚打完字触发的，离视线很近，动作越轻越好。
 *
 * @param {HTMLElement|null} row 一行消息（.row）
 * @param {number} dist 起始位置比终点低多少像素
 */
export function animateRowIn(row, dist = 10) {
  if (!HAS_ANIME || !row) return;
  animate(row, {
    opacity: [0, 1], translateY: [dist, 0], duration: 560, ease: "outCubic",
  });
}

/**
 * "正在思考"的三个小圆点：上下跳 + 明暗交替，无限循环。
 *
 * 这里的"跳"是**刻意保留**的 —— 它是"还在处理、别走开"的通用暗示，
 * 而且是三个 6px 的小点，动作幅度极小（4px），跟页面入场那种大块位移不是一回事。
 *
 * @param {HTMLElement|null} bubble 装着 .typing i 的气泡
 */
export function animateTyping(bubble) {
  if (!HAS_ANIME || !bubble) return;
  const dots = bubble.querySelectorAll(".typing i");
  if (!dots.length) return;
  animate(dots, {
    translateY: [-4, 0],
    opacity: [0.35, 1],
    delay: stagger(140),
    alternate: true,     // 到达终点后反向播回来，形成"呼吸"感
    loop: true,          // 一直播
    duration: 460,
    ease: "inOutSine",
  });
}

/**
 * 来源标签 + 耗时：轻微错落浮入。
 *
 * 这些元素数量不定（来源可能 1 个也可能 4 个），错落反而有"依次报账"的节奏，
 * 所以这里保留 stagger，只把幅度和时间调柔。
 *
 * @param {HTMLElement|null} row 一行消息（.row）
 */
export function animateMeta(row) {
  if (!HAS_ANIME || !row) return;
  const items = row.querySelectorAll(".src, .meta");
  if (!items.length) return;
  animate(items, {
    opacity: [0, 1], translateY: [5, 0], delay: stagger(60), duration: 460, ease: "outCubic",
  });
}
