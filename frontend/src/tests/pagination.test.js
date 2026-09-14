import { describe, expect, it } from 'vitest';
import {
  PAGE_HEIGHT,
  blockIndexOfAnchor,
  packIntoPages,
  pageClipHeight,
  pageIndexForBlock,
} from '../utils/pagination.js';

/** 按固定块高生成实测位置，省得每个用例手写 top / bottom。 */
function stack(heights, gap = 0) {
  let cursor = 0;
  return heights.map((height) => {
    const item = { top: cursor, bottom: cursor + height };
    cursor += height + gap;
    return item;
  });
}

describe('packIntoPages', () => {
  it('空内容返回一页空区间，而不是零页', () => {
    expect(packIntoPages([])).toEqual([{ start: 0, end: 0 }]);
    expect(packIntoPages(undefined)).toEqual([{ start: 0, end: 0 }]);
  });

  it('装得下时只有一页', () => {
    expect(packIntoPages(stack([300, 300]))).toEqual([{ start: 0, end: 2 }]);
  });

  it('装不下时按顺序切页，且每块只出现一次（不重不漏）', () => {
    const pages = packIntoPages(stack([400, 400, 400, 400, 400]));

    expect(pages.length).toBeGreaterThan(1);
    expect(pages[0].start).toBe(0);
    expect(pages[pages.length - 1].end).toBe(5);
    pages.forEach((page, i) => {
      expect(page.end).toBeGreaterThan(page.start); // 不产生空页
      if (i > 0) expect(page.start).toBe(pages[i - 1].end); // 与上一页首尾相接
    });
  });

  it('单个块比整页还高时独占一页，不被切断', () => {
    const pages = packIntoPages(stack([PAGE_HEIGHT * 2, 100, 100]));

    expect(pages[0]).toEqual({ start: 0, end: 1 });
  });

  it('段落之间的外边距计入页高（用 height 累加会算漏）', () => {
    // 三块各 200 高 + 两块间距 100：从首块顶到末块底共 800，超过一页 660
    const withGaps = stack([200, 200, 200], 100);
    const withoutGaps = stack([200, 200, 200]);

    expect(packIntoPages(withGaps)).toEqual([{ start: 0, end: 2 }, { start: 2, end: 3 }]);
    expect(packIntoPages(withoutGaps)).toEqual([{ start: 0, end: 3 }]);
  });

  it('量不到布局时（全是 0）合成一页，行为可预测', () => {
    // jsdom 没有排版引擎，getBoundingClientRect 全是 0——按 0 处理而不是乱切页
    expect(packIntoPages(stack([0, 0, 0]))).toEqual([{ start: 0, end: 3 }]);
  });

  it('页高非法时按一页处理，不产生除零之类的怪结果', () => {
    expect(packIntoPages(stack([10, 10]), 0)).toEqual([{ start: 0, end: 2 }]);
    expect(packIntoPages(stack([10, 10]), -5)).toEqual([{ start: 0, end: 2 }]);
  });

  it('非法位置按 0 计，不把 NaN 传染给分页结果', () => {
    const items = [{ top: 0, bottom: 100 }, { top: NaN, bottom: undefined }];

    expect(packIntoPages(items)).toEqual([{ start: 0, end: 2 }]);
  });
});

describe('pageClipHeight', () => {
  it('内容不足一页时按整页裁，翻页时纸张不会忽高忽低', () => {
    const items = stack([300, 300, 300]);
    expect(pageClipHeight(items, { start: 0, end: 2 })).toBe(PAGE_HEIGHT);
  });

  it('内容超过一页时按内容放行，多出来的部分不被裁掉', () => {
    const items = stack([PAGE_HEIGHT + 200]);
    expect(pageClipHeight(items, { start: 0, end: 1 })).toBe(PAGE_HEIGHT + 200);
  });

  it('首块超高时按该块高度放行，保证裁切不会切掉正文', () => {
    const items = stack([PAGE_HEIGHT * 2]);
    expect(pageClipHeight(items, { start: 0, end: 1 })).toBe(PAGE_HEIGHT * 2);
  });

  it('量不到布局时退回整页高，不会把纸张压成一条线', () => {
    expect(pageClipHeight(stack([0, 0]), { start: 0, end: 2 })).toBe(PAGE_HEIGHT);
  });
});

describe('pageIndexForBlock', () => {
  const pages = [{ start: 0, end: 2 }, { start: 2, end: 5 }];

  it('按下标落在哪一页', () => {
    expect(pageIndexForBlock(pages, 0)).toBe(0);
    expect(pageIndexForBlock(pages, 1)).toBe(0);
    expect(pageIndexForBlock(pages, 2)).toBe(1);
    expect(pageIndexForBlock(pages, 4)).toBe(1);
  });

  it('越界夹到首 / 末页，锚点跳转永远有落点', () => {
    expect(pageIndexForBlock(pages, -1)).toBe(0);
    expect(pageIndexForBlock(pages, 99)).toBe(1);
    expect(pageIndexForBlock([], 3)).toBe(0);
  });
});

describe('blockIndexOfAnchor', () => {
  const paragraphs = [
    { type: 'p', segs: [{ t: 'text', v: '前言' }] },
    { type: 'p', segs: [{ t: 'src', id: 'source-rate', v: '变化率' }] },
    { type: 'formula', parts: ['f(x)'] },
  ];

  it('找到带该锚点的段落', () => {
    expect(blockIndexOfAnchor(paragraphs, 'source-rate')).toBe(1);
  });

  it('找不到（如跨章依据）返回 -1，而不是误判成第 0 段', () => {
    expect(blockIndexOfAnchor(paragraphs, 'source-elsewhere')).toBe(-1);
    expect(blockIndexOfAnchor(paragraphs, '')).toBe(-1);
    expect(blockIndexOfAnchor(undefined, 'source-rate')).toBe(-1);
  });
});
