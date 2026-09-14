/**
 * 阅读器「分页视图」的排版计算。
 *
 * 教材段落长短不一、还夹着公式行，所以不能在数据层按固定条数切页，只能在渲染后
 * 按**实测位置**装箱：量出每个块相对正文区顶部的 `top` / `bottom`，交给
 * `packIntoPages` 贪心塞页，塞不下就翻页。
 *
 * 用 `bottom` 而不是 `height` 是因为段落之间有外边距（`p { margin-bottom }`），
 * `getBoundingClientRect().height` 不含外边距，累加高度会和真实位置越差越远。
 *
 * 这里只做纯计算、不碰 DOM：既方便单测，也保证 jsdom（量不到布局、全部是 0）
 * 下行为可预测——不会出现「页数随机」这种测不稳的情况。
 */

/** 单页容纳的正文高度（px）。与 study.css 里 `.paper` 的可视高度对应。 */
export const PAGE_HEIGHT = 660;

/**
 * 按各块的实测位置贪心装箱成页。
 *
 * @param {{top: number, bottom: number}[]} items 各块相对正文区顶部的位置（px，按顺序）
 * @param {number} pageHeight 单页可用高度
 * @returns {{start: number, end: number}[]} 每页覆盖的块下标区间，`end` 不含
 *
 * 约定：
 * - 位置为 0 或非法值按 0 计：jsdom 测不出布局时全部为 0，自然合成一页；
 * - **单个块比整页还高时它独占一页**，不做切割——切了会破坏划词与锚点定位，
 *   裁掉则意味着正文直接丢失（裁切高度见 `pageClipHeight`）；
 * - 空内容返回一页空区间而不是零页，省得调用方到处判空。
 */
export function packIntoPages(items, pageHeight = PAGE_HEIGHT) {
  const total = items?.length ?? 0;
  if (!total) return [{ start: 0, end: 0 }];
  if (!(pageHeight > 0)) return [{ start: 0, end: total }];

  const pages = [];
  let start = 0;
  for (let i = 1; i < total; i += 1) {
    // 从本页首块顶部量起，超出整页高度就换页。首块自己超高时，它与下一页
    // 首块的分界点落在它自己之后，于是自然独占一页、不会被切开。
    if (num(items[i].bottom) - num(items[start].top) > pageHeight) {
      pages.push({ start, end: i });
      start = i;
    }
  }
  pages.push({ start, end: total });
  return pages;
}

/**
 * 当前页该裁多高（px）——分页视图里纸张的可视高度。
 *
 * 至少要有一整页高，否则纸张会随内容忽高忽低、翻页时页面跳动；
 * 但**页里有超高块时必须按内容放行**，否则超出部分会被 `overflow: hidden` 吃掉。
 */
export function pageClipHeight(items, page, pageHeight = PAGE_HEIGHT) {
  const top = num(items?.[page?.start]?.top);
  const bottom = num(items?.[page.end - 1]?.bottom);
  return Math.max(pageHeight, bottom - top);
}

/** 块下标 → 页码（从 0 起）；越界时夹到首/末页，保证锚点跳转永远有落点。 */
export function pageIndexForBlock(pages, blockIndex) {
  if (!pages?.length) return 0;
  const found = pages.findIndex((page) => blockIndex >= page.start && blockIndex < page.end);
  if (found >= 0) return found;
  return blockIndex < 0 ? 0 : pages.length - 1;
}

/**
 * 找包含某个锚点的块下标：段落里带 `data-source-id` 的片段就是锚点。
 * 返回 -1 表示本章没有这个锚点（例如跨章依据跳到了别的章节）。
 */
export function blockIndexOfAnchor(paragraphs, anchorId) {
  if (!anchorId) return -1;
  return (paragraphs ?? []).findIndex((para) =>
    para?.segs?.some((seg) => seg?.t === 'src' && seg.id === anchorId),
  );
}

function num(value) {
  return Number.isFinite(value) ? value : 0;
}
