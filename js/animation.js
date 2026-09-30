import { animate, createTimeline, stagger } from "animejs"

/* animation.js —— 动效：页面入场 + 消息进出场动画 */

/* 动画库是否可用（本地文件 js/vendor/anime.min.js，不再走 CDN）。
   万一这个文件被误删，HAS_ANIME 会变成 false，
   下面每个动画函数都会直接 return —— 页面变朴素，但问答功能照常。
   绝对不让"动画库挂了"变成"整个页面不能用了"。 */
const HAS_ANIME = typeof animate !== "undefined";

/* —— 页面入场 —— */
/* 注意：这里是 .card（class），不是 #card。
   HTML 里写的是 <div class="card">，根本没有 id="card"，
   选择器写错的话这个卡片就永远等不到入场动画。 */
if (HAS_ANIME) {
  const intro = createTimeline();
  intro
    .add(".topbar", { opacity: [0, 1], translateY: [-12, 0], duration: 600, ease: "outQuad" })
    .add("h1", { opacity: [0, 1], translateY: [24, 0], duration: 780, ease: "outQuart" }, "-=350")
    .add(".sub", { opacity: [0, 1], translateY: [14, 0], duration: 640, ease: "outQuart" }, "-=520")
    .add(".badge", { opacity: [0, 1], translateY: [10, 0], delay: stagger(80), duration: 520, ease: "outQuart" }, "-=420")
    .add(".card", { opacity: [0, 1], translateY: [26, 0], scale: [0.985, 1], duration: 780, ease: "outQuart" }, "-=380")
    .add(".chip", { opacity: [0, 1], translateY: [10, 0], delay: stagger(90), duration: 480 }, "-=400");
}

/* —— 消息行淡入（dist = 浮动距离） —— */
export function animateRowIn(row, dist = 16) {
  if (!HAS_ANIME) return;
  animate(row, { opacity: [0, 1], translateY: [dist, 0], duration: 420, ease: "outQuart" });
}

/* —— 输入中圆点跳动 —— */
export function animateTyping(bubble) {
  if (!HAS_ANIME) return;
  animate(bubble.querySelectorAll(".typing i"), {
    translateY: [-5, 0], opacity: [0.35, 1],
    delay: stagger(140), alternate: true, loop: true,
    duration: 420, ease: "inOutSine"
  });
}

/* —— 来源标签 + 耗时浮入 —— */
export function animateMeta(row) {
  if (!HAS_ANIME) return;
  animate(row.querySelectorAll(".src, .meta"), { opacity: [0, 1], translateY: [6, 0], delay: stagger(90), duration: 380 });
}