/** 转义 HTML 特殊字符（聊天/问答展示时使用）。 */
export function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

/** 截断过长文本并追加省略号。 */
export function truncate(s, max = 34) {
  const text = String(s);
  return text.length > max ? text.slice(0, max) + '…' : text;
}
