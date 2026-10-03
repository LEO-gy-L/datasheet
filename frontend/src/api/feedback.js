import { FEEDBACKS, delay } from "@/mock/data.js";
import { request } from "./client.js";

/**
 * 反馈接口（用户侧提交/查看，管理员侧处理）
 * ======================================
 * 反馈的来路有两条，都要支持：
 *   ① 用户在「datasheet 助理」页，某条回答下面点「反馈」按钮 -> 带上那轮问答
 *   ② 直接进「问题反馈」页… —— 不需要，用户侧那个页面只查看，不新建
 *
 * 【现在】读写 mock/data.js；【接后端后】换成注释里的 request(...)。
 */

const STORE = [...FEEDBACKS]; // 内存里的一份副本，让"提交一条"能立刻出现在列表里

/** 状态中文名，页面和筛选器都用它 */
/* 状态标签色。全站是灰阶的，所以：
     · 待处理 / 处理中 -> 都用中性灰（靠文字区分即可，不需要两个颜色）
     · 已处理         -> 保留一点绿。这是全站唯一允许出现的彩色，
                         因为"已解决"值得一个正面反馈，用灰反而像没做完。 */
export const FEEDBACK_STATUS = {
  pending: { label: "待处理", color: "default" },
  processing: { label: "处理中", color: "default" },
  resolved: { label: "已处理", color: "success" },
};

/** 反馈分类选项（提交弹窗里的下拉框） */
export const FEEDBACK_CATEGORIES = [
  "答案不准",
  "检索不到",
  "格式错乱",
  "回答太慢",
  "其他",
];

/**
 * 反馈列表。
 *
 * @param {object} options
 *   username  只取这个用户提交的（用户侧传自己的用户名；管理员侧不传 = 全部）
 *   status    'pending' | 'processing' | 'resolved'，不传 = 全部
 *
 * 【接后端后】
 *   const qs = new URLSearchParams();
 *   if (username) qs.set("username", username);
 *   if (status) qs.set("status", status);
 *   return request(`/feedbacks?${qs}`);
 */
export async function listFeedbacks({ username, status } = {}) {
  let rows = [...STORE];
  if (username) rows = rows.filter((r) => r.username === username);
  if (status) rows = rows.filter((r) => r.status === status);
  // 新的排前面
  rows.sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1));
  return delay(rows);
}

/**
 * 提交一条反馈（用户侧，从助理页的反馈按钮进来）。
 *
 * 【接后端后】return request("/feedbacks", { method: "POST", body: payload });
 */
export async function createFeedback(payload) {
  const row = {
    id: Date.now(),
    status: "pending",
    reply: "",
    repliedAt: "",
    createdAt: formatNow(),
    ...payload,
  };
  STORE.unshift(row);
  return delay(row, 320);
}

/**
 * 管理员回复 / 改状态。
 * 【接后端后】return request(`/feedbacks/${id}`, { method: "PUT", body: { status, reply } });
 */
export async function replyFeedback(id, { status, reply }) {
  const row = STORE.find((r) => r.id === id);
  if (row) {
    if (status) row.status = status;
    if (reply !== undefined) row.reply = reply;
    if (status === "resolved") row.repliedAt = formatNow();
  }
  return delay(row, 320);
}

/** 生成 "2026-10-03 18:20" 这种格式的当前时间 */
function formatNow() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

// 接后端后删掉这行
void request;
