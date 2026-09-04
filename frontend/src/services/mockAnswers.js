/**
 * 问答模拟器：根据关键词返回演示答案。
 * 接入真实后端后，此逻辑由模型服务替代（见 services/api.js 的 ask）。
 *
 * @param {string} question 用户问题
 * @param {{selectedText?: string}} context 选中的原文上下文（可选）
 * @returns {{ text: string, sources: string[] }} 回答文本 + 教材锚点 id 列表
 */
export function answerFor(question, context = {}) {
  const q = String(question);

  if (q.includes('极限') || q.includes('为什么')) {
    return {
      text: '因为我们要描述的是「某一瞬间」的变化，而平均变化率一定跨着一段区间。让 Δx 不断变小，才能把这段区间压缩到目标时刻；极限存在，说明逼近的结果是稳定、唯一的。',
      sources: ['source-limit'],
    };
  }

  return {
    text: '这段话先定义了自变量的增量 Δx，再由它得到函数增量 Δy。接下来用 Δy / Δx 表示平均变化率；当 Δx 趋近于 0 时，它的极限就是导数。你可以继续追问其中任一个符号。',
    sources: ['source-rate', 'source-limit'],
  };
}
