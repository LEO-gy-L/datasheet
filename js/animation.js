/* animation.js —— 动效：页面入场 + 消息进出场动画 */

/* 动画库是否可用（本地文件 js/vendor/anime.min.js，不再走 CDN）。
   万一这个文件被误删，HAS_ANIME 会变成 false，
   下面每个动画函数都会直接 return —— 页面变朴素，但问答功能照常。
   绝对不让"动画库挂了"变成"整个页面不能用了"。 */
const HAS_ANIME = typeof anime !== "undefined";

/* —— 页面入场 —— */
/* 注意：这里是 .card（class），不是 #card。
   HTML 里写的是 <div class="card">，根本没有 id="card"，
   选择器写错的话这个卡片就永远等不到入场动画。 */
if (HAS_ANIME) {
  const intro = anime.timeline();
  intro
    .add({ targets: ".topbar", opacity: [0, 1], translateY: [-12, 0], duration: 600, easing: "easeOutQuad" })
    .add({ targets: "h1", opacity: [0, 1], translateY: [24, 0], duration: 780, easing: "easeOutQuart" }, "-=350")
    .add({ targets: ".sub", opacity: [0, 1], translateY: [14, 0], duration: 640, easing: "easeOutQuart" }, "-=520")
    .add({ targets: ".badge", opacity: [0, 1], translateY: [10, 0], delay: anime.stagger(80), duration: 520, easing: "easeOutQuart" }, "-=420")
    .add({ targets: ".card", opacity: [0, 1], translateY: [26, 0], scale: [.985, 1], duration: 780, easing: "easeOutQuart" }, "-=380")
    .add({ targets: ".chip", opacity: [0, 1], translateY: [10, 0], delay: anime.stagger(90), duration: 480 }, "-=400");
}

/* —— 消息行淡入（dist = 浮动距离） —— */
function animateRowIn(row, dist = 16) {
  if (!HAS_ANIME) return;
  anime({ targets: row, opacity: [0, 1], translateY: [dist, 0], duration: 420, easing: "easeOutQuart" });
}

/* —— 输入中圆点跳动 —— */
function animateTyping(bubble) {
  if (!HAS_ANIME) return;
  anime({
    targets: bubble.querySelectorAll(".typing i"),
    translateY: [-5, 0], opacity: [.35, 1],
    delay: anime.stagger(140), direction: "alternate", loop: true,
    duration: 420, easing: "easeInOutSine"
  });
}

/* —— 来源标签 + 耗时浮入 —— */
function animateMeta(row) {
  if (!HAS_ANIME) return;
  anime({ targets: row.querySelectorAll(".src, .meta"), opacity: [0, 1], translateY: [6, 0], delay: anime.stagger(90), duration: 380 });
}
