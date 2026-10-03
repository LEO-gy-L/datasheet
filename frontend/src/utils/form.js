/**
 * 表单小工具
 * ==========
 * 只有一个函数，但它解决一个很容易踩、报错又不明显的坑。
 *
 * ---------------------------------------------------------------------------
 * 坑是这样的：
 *
 *   async function save() {
 *     const values = await form.validateFields();   // ①
 *     ...
 *   }
 *   <Button onClick={save} />                       // ②
 *
 * 字段没填对时，① 里的 validateFields() 会 **reject**（抛错）。
 * 这个错没人接：② 处 React 只是"调用一下 onClick"，它不管返回的 Promise，
 * 于是这个 rejection 就一路飘到浏览器 —— 控制台里出现一条
 *
 *     Uncaught (in promise) Object
 *
 * 页面功能其实是好的（字段下面照样显示红字提示），但控制台里那条红字
 * 会让人以为程序崩了，排查起来还很难找 —— 因为它指向的行号是
 * "await validateFields()"，看起来完全无辜。
 *
 * 所以规矩是：**校验失败是"正常的业务分支"，不是异常**，
 * 应当在这里就地拦住，而不是让异常冒出去。
 * ---------------------------------------------------------------------------
 *
 * @param {object} form antd 的 Form 实例（Form.useForm() 拿到的那个）
 * @returns {Promise<object|null>} 校验通过返回字段值；没通过返回 null
 *
 * 用法：
 *   const values = await safeValidate(form);
 *   if (!values) return;   // 没通过，红字提示 antd 已经画好了，直接收工
 */
export async function safeValidate(form) {
  try {
    return await form.validateFields();
  } catch {
    // 故意吞掉：校验失败时 antd 已经在每个出错字段下面显示了具体原因，
    // 这里再弹一个 message 反而是重复打扰。
    return null;
  }
}
