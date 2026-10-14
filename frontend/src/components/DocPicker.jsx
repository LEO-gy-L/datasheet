import { FileTextOutlined, LoadingOutlined } from "@ant-design/icons";
import { Popover, Tooltip } from "antd";
import { useCallback, useEffect, useState } from "react";

import { documentOptions } from "@/api/docs.js";

/**
 * 手册选择器（"只在这份 PDF 里检索"）
 * ==================================
 * 位置在输入栏上方，长得像一个胶囊按钮：`📄 全部手册 ⌄`。
 * 点开是一个列表：第一项是"全部手册"，其余是每份已入库的手册。
 *
 * 为什么把它做成"选择范围"而不是"选择模型"
 * ------------------------------------------
 *   它控制的东西**不是模型**，而是检索的范围 ——
 *   后端 /api/ask 的 source 参数，会一路传到向量库的 metadata 过滤上
 *   （见 retrieval/hybrid.py 里 `self.chunks[doc_i].source != source` 那句）。
 *   选"全部手册"时后端收到 source = null，就在所有手册里检索。
 *
 *   所以文案不能说成"选择模型"，否则用户会以为换了个 AI。
 *   它更像搜索引擎的"限定站点"。
 *
 * 为什么选中后要**清空当前对话**
 * ------------------------------------------
 *   这是个刻意的选择。换范围之后，新问题的检索范围变了，
 *   但屏幕上那些旧回答是在**旧范围**下得出的 ——
 *   两批答案混在一起，用户回头再看会分不清哪句是哪个范围给的，
 *   很容易误以为"同一个问题前后答案矛盾"。
 *   清空会让"范围"这件事在视觉上有个明确的分界。
 *   （提示里说明了这一点，不是悄悄清掉。）
 *
 * @param {string}  value     当前选中的文件名，"" 表示全部手册
 * @param {Function} onChange 选中变化时的回调
 */
export default function DocPicker({ value, onChange, disabled }) {
  const [options, setOptions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setOptions(await documentOptions());
    } catch {
      /* 拉失败时**故意不弹错误提示**：
         这个列表是"锦上添花"的功能，拉不到就退化成"只有全部手册"，
         问答本身完全不受影响。为了一个附加功能在页面右上角弹一条红字，
         会让用户以为整个系统坏了 —— 得不偿失。
         真要排查的话，Network 面板里那条 4xx 一直都在。 */
      setOptions([]);
    } finally {
      setLoading(false);
    }
  }, []);

  // 挂载时拉一次。
  // 每次点开时**不**重新拉 —— 建库是低频操作，
  // 列表在页面停留期间基本不会变；每次点开都请求一次纯属浪费。
  // 想看到新建的库，刷新一下页面即可。
  useEffect(() => {
    load();
  }, [load]);

  /* 找到当前选中项，拿它的页数/块数显示在气泡里。
     用 find 而不是按下标取 —— 列表顺序是按文件名排的，
     新入库一份手册就会把它前面的项挤位，按下标存就取错了。 */
  const current = options.find((o) => o.value === value);

  const pick = (next) => {
    setOpen(false);
    if (next === value) return;      // 选了同一个，不做任何事（也不清空对话）
    onChange(next);
  };

  const content = (
    <div className="docmenu">
      <div
        className={`docmenu-item ${value ? "" : "active"}`}
        onClick={() => pick("")}
      >
        <span className="docmenu-name">全部手册</span>
        <span className="docmenu-meta">在所有已入库的手册里检索</span>
      </div>

      {options.length > 0 && <div className="docmenu-sep" />}

      {options.map((o) => (
        <div
          key={o.value}
          className={`docmenu-item ${value === o.value ? "active" : ""}`}
          onClick={() => pick(o.value)}
        >
          <span className="docmenu-name">{o.label}</span>
          <span className="docmenu-meta">
            {o.pages ? `${o.pages} 页 · ` : ""}
            {o.chunks} 个片段
          </span>
        </div>
      ))}

      {!loading && options.length === 0 && (
        <div className="docmenu-empty">
          还没有已入库的手册。请管理员先去「文档入库」页建库。
        </div>
      )}
    </div>
  );

  return (
    <div className="docpicker">
      <Popover
        content={content}
        trigger="click"
        placement="topLeft"
        open={open}
        onOpenChange={(v) => !disabled && setOpen(v)}
        // 关掉 antd 自带的小箭头：这个气泡是从按钮正上方弹出的，
        // 箭头指着按钮反而让视线在"按钮 → 箭头 → 弹层"之间多跳一次。
        arrow={false}
        // 覆盖层挂到 .ds-assistant 里，才能吃到这一页自己的 CSS 变量
        // （--surface / --line 都定义在 .ds-assistant 作用域内，
        //   挂到 body 上就取不到了，弹层会变成一片没有边框的白色）
        getPopupContainer={() => document.querySelector(".ds-assistant") || document.body}
      >
        <button
          type="button"
          className={`docpicker-btn ${open ? "open" : ""} ${value ? "active" : ""}`}
          disabled={disabled}
        >
          {loading ? (
            <LoadingOutlined style={{ fontSize: 12 }} />
          ) : (
            <FileTextOutlined style={{ fontSize: 12 }} />
          )}

          <span className="docpicker-label">
            {/* 文件名很长（CH32F103_Datasheet_CN.pdf），用 Tooltip 兜住完整内容，
                按钮上只显示截断后的 —— 不然它会把输入框挤没 */}
            <Tooltip title={current?.label || ""} mouseEnterDelay={0.4}>
              {current ? current.label : "全部手册"}
            </Tooltip>
          </span>

          <svg
            className="docpicker-caret"
            width="10"
            height="10"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M6 9l6 6 6-6" />
          </svg>
        </button>
      </Popover>
    </div>
  );
}
