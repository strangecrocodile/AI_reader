/**
 * 「PDF 页 ↔ 原文锚点」的对应关系。
 *
 * 原版 PDF 阅读面渲染的是**原书页面**，页面上没有锚点 id；而划词提问、笔记、
 * 依据回跳、按页上报已读全都建立在锚点上（`anchors.id`，如 `b1-s2-9`）。
 * 两边靠**页码 + 文本**这层对应接起来：
 *
 * - 后端在章节内容的每个段落上带了 `page`（见 serializers.chapter_content），
 *   扫描件那个页码是**印刷页码**，要减掉 `pageOffset` 才是 PDF 页序；
 * - 选中一段文字时，在它所在的那一页（含前后各一页，选区可能跨页）里找
 *   「包含它」的段落，取其中最长的那个——最长即最具体，命中率也最高。
 *
 * 为什么是文本匹配而不是 bbox：解析阶段没有把 span 的坐标落库（PyMuPDF 有，
 * 但老数据要重新解析）。文本匹配在绝大多数段落上够用，匹配不上时如实降级为
 * 空锚点——**提问仍然可用**，只是少掉「这一段就是首条证据」那一层加权。
 */

/** 匹配率低于这个值就不认：宁可不给锚点，也不给一个错的。 */
export const MIN_MATCH_RATIO = 0.6;

/**
 * 归一化：去空白、全角转半角、去掉连字符断词。
 *
 * PDF 的文字层会把一行的结尾断开（`函数与极\n限`），后端抽取出来的段落却是连着的；
 * 不统一处理，两边永远对不上。标点也一并抹掉——字形差异（`，` vs `,`）比文字差异
 * 常见得多，而它对「这是同一段吗」的判定没有帮助。
 */
export function normalizeForMatch(value) {
  return String(value ?? '')
    .replace(/[\uFF01-\uFF5E]/g, (ch) => String.fromCharCode(ch.charCodeAt(0) - 0xfee0))
    .replace(/[\s\u3000]+/g, '')
    .replace(/[-\u2010-\u2015]/g, '')
    .replace(
      /[.,;:!?'"()[\]{}<>/\\|~`@#$%^&*+=_\u3001\u3002\uFF0C\uFF1B\uFF1A\uFF01\uFF1F\u2018\u2019\u201C\u201D\u300A\u300B\u3008\u3009\u3010\u3011\u2026\u00B7]/g,
      '',
    );
}

/** 供归一化后做包含判断的最小长度：太短的选择（如「函数」）不参与匹配。 */
export const MIN_SELECTION_CHARS = 4;

/**
 * 锚点文本（段落纯文本）。
 *
 * 段落有两种形状：带版式的（锚点在 `segs[0]`，正文在子片段里，见 serializers）
 * 与不带版式的（正文直接在 `segs[0].v`）。插图/表格则把锚点放在 `id` 上。
 */
export function anchorTextOf(para) {
  if (!para) return '';
  if (para.type === 'image') return String(para.caption ?? '');
  if (para.type === 'table') {
    return (para.rows ?? []).map((row) => (row ?? []).join(' ')).join(' ');
  }
  const parts = [];
  for (const seg of para.segs ?? []) {
    if (!seg) continue;
    if (seg.v) parts.push(seg.v);
    for (const inner of seg.segs ?? []) {
      if (inner?.v) parts.push(inner.v);
    }
  }
  return parts.join('');
}

/** 段落锚点 id：与 Reader 的 `anchorIdOf` 同一套口径（图片/表格在 `id` 上）。 */
export function anchorIdOf(para) {
  if (!para) return '';
  if (para.type === 'image' || para.type === 'table') return para.id ?? '';
  const seg = (para.segs ?? []).find((item) => item && item.t === 'src');
  return seg?.id ?? '';
}

/**
 * 页码换算：后端给的是（可能经过印刷页码修正的）页码，阅读面要的是 PDF 页序。
 *
 * `pageOffset` 是「印刷页码 − PDF 页序」（见 parsing/ocr_pdf.py）：书上第 9 页
 * 若印在 PDF 第 17 页上，偏移是 8，那么 9 − 8 = 1... 反过来才对——后端存下来的
 * `page` 是印刷页码，所以 `pdf 页 = 印刷页 − offset`。
 */
export function pdfPageOf(page, pageOffset = 0) {
  const value = Number(page);
  if (!Number.isFinite(value)) return 0;
  return Math.max(1, Math.round(value) - (Number(pageOffset) || 0));
}

/**
 * 段落按 PDF 页码归组。
 *
 * 返回的 Map 键是 PDF 页序，值是 `{anchorId, text, raw}` 数组，按阅读顺序排列。
 */
export function pageAnchorsOf(paragraphs, pageOffset = 0) {
  const byPage = new Map();
  for (const para of paragraphs ?? []) {
    const anchorId = anchorIdOf(para);
    if (!anchorId) continue;
    const page = pdfPageOf(para.page, pageOffset);
    const text = anchorTextOf(para);
    if (!byPage.has(page)) byPage.set(page, []);
    byPage.get(page).push({ anchorId, text, raw: text, normalized: normalizeForMatch(text) });
  }
  return byPage;
}

/** 一段文字被包含在另一段里？两边都已归一化。 */
function contains(haystack, needle) {
  if (!needle) return false;
  return haystack.includes(needle);
}

/**
 * 选区 → 锚点。
 *
 * 先在**本页**找「包含选区」的段落，取其中最长的那个；本页找不到再看前后各一页
 * （选区可以跨页，文字层的行序也不总与段落顺序一致）。都不包含时退一步看重叠率：
 * 选区被截断（跨段落拖选、行尾断字）时仍能认出主要落点，低于阈值则返回空串。
 *
 * 返回 `{anchorId, page, ratio}`；`anchorId` 为空串表示没认出来。
 */
export function matchAnchorForSelection(byPage, page, selectedText) {
  const needle = normalizeForMatch(selectedText);
  const empty = { anchorId: '', page, ratio: 0 };
  if (needle.length < MIN_SELECTION_CHARS) return empty;

  const candidates = [];
  for (const offset of [0, -1, 1, -2, 2]) {
    const entries = byPage.get(page + offset);
    if (!entries?.length) continue;
    // 本页优先：同一段文字在邻页也出现时，别把用户带离他正在看的那一页
    const weight = offset === 0 ? 1 : 0.5;
    for (const entry of entries) {
      if (contains(entry.normalized, needle)) {
        candidates.push({ ...entry, ratio: 1, weight });
        continue;
      }
      const ratio = overlapRatio(entry.normalized, needle);
      if (ratio > 0) candidates.push({ ...entry, ratio, weight });
    }
    if (candidates.some((item) => item.ratio === 1 && item.weight === 1)) break;
  }

  if (!candidates.length) return empty;
  candidates.sort(
    (a, b) =>
      b.ratio * b.weight - a.ratio * a.weight ||
      b.normalized.length - a.normalized.length,
  );
  const best = candidates[0];
  if (best.ratio < MIN_MATCH_RATIO) return empty;
  return { anchorId: best.anchorId, page, ratio: best.ratio };
}

/**
 * 两个归一化字符串的重叠率：以**选区**为分母。
 *
 * 分母取选区而不是段落：段落往往比选区长得多，用段落做分母会让「选中的是段落的
 * 一小半」被判成不匹配。反过来（选区横跨两段）也会得到较低的分值，正是想要的。
 */
export function overlapRatio(paragraph, needle) {
  if (!paragraph || !needle) return 0;
  if (paragraph === needle) return 1;
  const shorter = paragraph.length < needle.length ? paragraph : needle;
  const longer = paragraph.length < needle.length ? needle : paragraph;
  // 最长公共子串：O(n*m) 但两边都只有几十到几百字，够用且无依赖
  let best = 0;
  let previous = new Array(shorter.length + 1).fill(0);
  for (let i = 1; i <= longer.length; i += 1) {
    const current = new Array(shorter.length + 1).fill(0);
    for (let j = 1; j <= shorter.length; j += 1) {
      if (longer[i - 1] === shorter[j - 1]) {
        current[j] = previous[j - 1] + 1;
        if (current[j] > best) best = current[j];
      }
    }
    previous = current;
  }
  return best / needle.length;
}

/** 锚点 → 它所在的 PDF 页；找不到返回 0。 */
export function pdfPageOfAnchor(byPage, anchorId) {
  if (!anchorId) return 0;
  for (const [page, entries] of byPage) {
    if (entries.some((entry) => entry.anchorId === anchorId)) return page;
  }
  return 0;
}
