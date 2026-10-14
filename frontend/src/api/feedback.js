import { request } from "./client.js";

/**
 * 反馈接口（用户侧提交/查看，管理员侧处理）
 * ======================================
 * 【2026-10-03】从 mock 换成真后端，后端在 backend/app/api/feedback.py。
 *
 * 反馈的来路只有一条：
 *   用户在「datasheet 助理」页某条回答下面点「反馈」按钮 → 带上那轮问答一起提交。
 *   （用户侧那个「问题反馈」页只查看，不新建 —— 因为脱离具体回答的反馈
 *     会让管理员看不懂在说什么。）
 */

/** 状态中文名 + 标签色。页面和筛选器都用它 */
/* 全站是灰阶的，所以：
     · 待处理 / 处理中 -> 都用中性灰（靠文字区分即可，不需要两个颜色）
     · 已处理         -> 保留一点绿。这是全站唯一允许出现的彩色，
                         因为"已解决"值得一个正面反馈，用灰反而像没做完。 */
export const FEEDBACK_STATUS = {
  pending: { label: "待处理", color: "default" },
  processing: { label: "处理中", color: "default" },
  resolved: { label: "已处理", color: "success" },
};

/** 反馈分类选项（提交弹窗里的下拉框）
    ⚠️ 后端也有一份同样的列表（backend/app/models/feedback.py 的 CATEGORIES），
       两边要同步改 —— 不过后端那份现在只作说明用，没有强制校验，
       所以「改这里忘了改后端」不会报错，只是后端少了那份参考。 */
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
 *   status   'pending' | 'processing' | 'resolved'，不传 = 全部
 *   username ⚠️ **现在会被忽略** —— 保留这个参数只是为了让调用处不改代码。
 *            谁的数据由服务端的 token 决定：
 *              管理员  → 返回全部人的
 *              普通用户 → 只返回自己的
 *            这也意味着"前端传谁的 username 都没用"，越权在接口层面就不可能发生。
 */
export async function listFeedbacks({ status } = {}) {
  const qs = new URLSearchParams();
  if (status) qs.set("status", status);
  const q = qs.toString();
  return request(`/feedbacks${q ? `?${q}` : ""}`);
}

/**
 * 提交一条反馈（用户侧，从助理页的反馈按钮进来）。
 *
 * payload: { category, content, question, answer }
 *   ⚠️ 无需传 username —— 后端从 token 取当前用户。
 *      前端调用处现在仍然传了它（mock 时代的写法），后端会忽略这个多余字段。
 *      留着不改是为了让 Assistant.jsx 保持原样；哪天顺手清理掉也没问题。
 */
export async function createFeedback(payload) {
  return request("/feedbacks", { method: "POST", body: payload });
}

/**
 * 管理员回复 / 改状态。
 * @param {number} id
 * @param {object} patch { status, reply }
 *
 * 只传 status 时（"仅保存，标记处理中"）不会写回复时间 ——
 * 那是后端的规则，见 feedback_service.update 里的注释。
 */
export async function replyFeedback(id, { status, reply }) {
  return request(`/feedbacks/${id}`, { method: "PUT", body: { status, reply } });
}
