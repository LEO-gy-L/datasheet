/**
 * 前端假数据（mock）
 * ================
 * 为什么存在：
 *   这一轮只改前端 —— 后端目前只有 /api/health 和 /api/ask 两个接口，
 *   没有用户、文档、反馈的接口。所以「入库 / 用户管理 / 反馈」这些页面
 *   先用这里的数据顶着，界面和交互可以先做完、先跑起来。
 *
 * 怎么换成真后端：
 *   api/ 目录下每个函数里都写了【接后端后】那一行注释。
 *   把 return 换成那个 request(...) 调用就行，**页面代码一个字都不用改** ——
 *   因为函数的返回结构是照着"以后接口会长什么样"定的。
 *
 * 唯一的例外：`ask()`（问答）后端已经做好了，走的是真接口，不是假数据。
 */

/** 把同步值包成异步，并加一点延迟 —— 模拟真实网络请求，方便看到 loading 效果 */
export function delay(value, ms = 220) {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms));
}

/** 可以登录的账号。后端做好后由 /api/auth/login 校验，这里只用于本地演示 */
export const ACCOUNTS = [
  {
    username: "admin",
    password: "admin123",
    role: "admin",
    name: "管理员",
    email: "admin@datasheet.local",
  },
  {
    username: "zhang",
    password: "123456",
    role: "user",
    name: "小张",
    email: "zhang@datasheet.local",
  },
];

/** 已入库的文档（对应管理员「入库」页的表格） */
export const DOCUMENTS = [
  {
    id: 1,
    name: "CH32F103_Datasheet_CN.pdf",
    size: 2516582,
    type: "pdf",
    indexed: true,
    pages: 28,
    chunks: 115,
    createdAt: "2026-10-03 17:52",
  },
  {
    id: 2,
    name: "STM32F103C8_Datasheet.pdf",
    size: 4210688,
    type: "pdf",
    indexed: true,
    pages: 113,
    chunks: 812,
    createdAt: "2026-09-29 10:04",
  },
  {
    id: 3,
    name: "ATmega328P_Datasheet.pdf",
    size: 5242880,
    type: "pdf",
    indexed: true,
    pages: 294,
    chunks: 864,
    createdAt: "2026-09-28 22:31",
  },
  {
    id: 4,
    name: "CH32V003_参考手册.pdf",
    size: 8123456,
    type: "pdf",
    indexed: false,
    pages: 0,
    chunks: 0,
    createdAt: "2026-10-03 18:02",
  },
  {
    id: 5,
    name: "GPIO_应用笔记.txt",
    size: 20480,
    type: "txt",
    indexed: false,
    pages: 0,
    chunks: 0,
    createdAt: "2026-10-03 18:05",
  },
];

/** 平台用户（对应管理员「用户管理 → 账号管理」） */
export const USERS = [
  {
    id: 1,
    username: "admin",
    name: "管理员",
    role: "admin",
    email: "admin@datasheet.local",
    createdAt: "2026-09-23",
    lastLogin: "2026-10-03 18:12",
    status: "active",
  },
  {
    id: 2,
    username: "zhang",
    name: "小张",
    role: "user",
    email: "zhang@datasheet.local",
    createdAt: "2026-09-25",
    lastLogin: "2026-10-03 17:40",
    status: "active",
  },
  {
    id: 3,
    username: "li",
    name: "小李",
    role: "user",
    email: "li@datasheet.local",
    createdAt: "2026-09-27",
    lastLogin: "2026-10-02 21:05",
    status: "active",
  },
  {
    id: 4,
    username: "wang",
    name: "小王",
    role: "user",
    email: "wang@datasheet.local",
    createdAt: "2026-10-01",
    lastLogin: "2026-10-01 09:12",
    status: "disabled",
  },
];

/**
 * 用户提交的反馈。
 *
 * status 三个状态的含义：
 *   pending     刚提交，管理员还没看
 *   processing  管理员已读、正在处理
 *   resolved    已处理完，会带一条 reply（管理员回复）
 *
 * 数据结构里同时存了 question / answer —— 因为反馈是从
 * "助理页某条回答下面的反馈按钮"发出来的，得知道用户是针对哪一轮回答不满。
 */
export const FEEDBACKS = [
  {
    id: 1,
    username: "zhang",
    category: "答案不准",
    question: "CH32F103C6T6 的引脚数是多少？",
    answer: "CH32F103C6T6 共 48 个引脚，闪存 32K 字节。",
    content:
      "回答里写「32K 字节」，手册原文是 32KB Flash，表述不一致，容易让人误解成 32K bit。",
    status: "resolved",
    reply: "已调整提示词中的单位表述，统一按手册原文输出。感谢反馈。",
    createdAt: "2026-10-03 15:20",
    repliedAt: "2026-10-03 16:02",
  },
  {
    id: 2,
    username: "zhang",
    category: "检索不到",
    question: "睡眠模式下的电流消耗是多少？",
    answer: "抱歉，检索到的片段里没有相关数据。",
    content: "第 23 页有一张睡眠模式电流表，应该是能检索到的。",
    status: "processing",
    reply: "",
    createdAt: "2026-10-02 20:11",
    repliedAt: "",
  },
  {
    id: 3,
    username: "li",
    category: "格式错乱",
    question: "引脚定义表给我看看",
    answer: "（表格 markdown 有错位）",
    content: "表格里有一列串行了，表头对不上数据。",
    status: "resolved",
    reply: "表格已按坐标重建，横向合并单元格现在只填最左列，不再串行。",
    createdAt: "2026-10-01 11:35",
    repliedAt: "2026-10-02 09:18",
  },
  {
    id: 4,
    username: "wang",
    category: "其他",
    question: "能不能加个导出功能？",
    answer: "（这是一个功能建议）",
    content: "希望对话内容能一键导出成 markdown。",
    status: "pending",
    reply: "",
    createdAt: "2026-10-03 17:58",
    repliedAt: "",
  },
];
