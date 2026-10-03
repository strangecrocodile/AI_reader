import { describe, expect, it } from 'vitest';

import {
  MIN_MATCH_RATIO,
  anchorIdOf,
  anchorTextOf,
  matchAnchorForSelection,
  normalizeForMatch,
  overlapRatio,
  pageAnchorsOf,
  pdfPageOf,
  pdfPageOfAnchor,
} from '../utils/anchorPage.js';

/**
 * 「PDF 页 ↔ 锚点」的映射。
 *
 * 原版 PDF 页面上没有锚点 id，只能靠页码 + 文本把用户选中的那段认回某个锚点。
 * 这套映射错了不会报错，只会让划词提问悄悄少掉「这一段就是首条证据」那层加权，
 * 或者把依据回跳到隔壁一页——所以这里把每条判定都钉住。
 */

/** 造一个带版式的段落（锚点在 segs[0]，正文在子片段里）。 */
function styledPara(page, id, text, extra = []) {
  return {
    type: 'p',
    page,
    segs: [
      { t: 'src', id, v: '', segs: [{ t: 'text', v: text }, ...extra] },
    ],
  };
}

/** 造一个没有版式的段落（正文直接放在锚点上）。 */
function plainPara(page, id, text) {
  return { type: 'p', page, segs: [{ t: 'src', id, v: text }] };
}

describe('normalizeForMatch', () => {
  it('去掉空白与全角空格', () => {
    expect(normalizeForMatch('函数 与\u3000极限')).toBe('函数与极限');
  });

  it('全角标点转半角后再抹掉标点', () => {
    // 字形差异（，vs ,）比文字差异常见得多，对「这是同一段吗」没有帮助
    expect(normalizeForMatch('导数，是变化率。')).toBe('导数是变化率');
  });

  it('去掉断词连字符：PDF 文字层会把一行拆成两半', () => {
    expect(normalizeForMatch('func-\ntion')).toBe('function');
  });

  it('空值与数字不报错', () => {
    expect(normalizeForMatch(null)).toBe('');
    expect(normalizeForMatch(undefined)).toBe('');
    expect(normalizeForMatch(42)).toBe('42');
  });
});

describe('anchorTextOf / anchorIdOf', () => {
  it('带版式的段落：正文在子片段里，拼起来就是这一段', () => {
    const para = styledPara(3, 'b1-s2-7', '设 f(x) 的导数为 ', [{ t: 'run', v: '0', style: ['sub'] }]);
    expect(anchorTextOf(para)).toBe('设 f(x) 的导数为 0');
    expect(anchorIdOf(para)).toBe('b1-s2-7');
  });

  it('无版式的段落：正文直接放在锚点上', () => {
    const para = plainPara(3, 'b1-s2-8', '这是一段没有任何格式的正文。');
    expect(anchorTextOf(para)).toBe('这是一段没有任何格式的正文。');
    expect(anchorIdOf(para)).toBe('b1-s2-8');
  });

  it('插图用图注、表格用单元格文字，锚点在 id 上', () => {
    expect(anchorTextOf({ type: 'image', id: 's1', caption: '图 1-1 函数图像' })).toBe('图 1-1 函数图像');
    expect(anchorIdOf({ type: 'image', id: 's1' })).toBe('s1');
    expect(anchorTextOf({ type: 'table', id: 's2', rows: [['概念', '含义']] })).toBe('概念 含义');
    expect(anchorIdOf({ type: 'table', id: 's2' })).toBe('s2');
  });

  it('没有锚点的段落不参与映射', () => {
    expect(anchorIdOf({ type: 'p', segs: [{ t: 'text', v: 'x' }] })).toBe('');
  });
});

describe('pdfPageOf', () => {
  it('扫描件要减掉偏移：书上第 9 页印在 PDF 第 17 页时，偏移是 8', () => {
    expect(pdfPageOf(17, 8)).toBe(9);
  });

  it('文本型 PDF 与 Word 没有偏移', () => {
    expect(pdfPageOf(9)).toBe(9);
    expect(pdfPageOf(9, 0)).toBe(9);
  });

  it('减到 0 以下也不给负数页码', () => {
    expect(pdfPageOf(3, 10)).toBe(1);
  });

  it('脏数据不炸：非数字按第 1 页处理', () => {
    expect(pdfPageOf(undefined)).toBe(0);
    expect(pdfPageOf('abc')).toBe(0);
  });
});

describe('pageAnchorsOf', () => {
  it('按 PDF 页归组，偏移一并换算', () => {
    const byPage = pageAnchorsOf(
      [styledPara(11, 'a1', '第一段'), plainPara(11, 'a2', '第二段'), plainPara(12, 'a3', '第三段')],
      2,
    );
    expect([...byPage.keys()]).toEqual([9, 10]);
    expect(byPage.get(9).map((entry) => entry.anchorId)).toEqual(['a1', 'a2']);
    expect(byPage.get(10).map((entry) => entry.anchorId)).toEqual(['a3']);
  });

  it('没有锚点的段落被跳过', () => {
    const byPage = pageAnchorsOf([{ type: 'p', page: 1, segs: [{ t: 'text', v: '无锚点' }] }]);
    expect(byPage.size).toBe(0);
  });
});

describe('matchAnchorForSelection', () => {
  const byPage = pageAnchorsOf([
    plainPara(4, 'p4-a', '函数在某点的导数，就是该点切线的斜率。'),
    plainPara(4, 'p4-b', '导数的几何意义是曲线在这一点的切线斜率，这一点很重要。'),
    plainPara(5, 'p5-a', '极限是微积分中第一个重要的工具，它描述了无限逼近的过程。'),
  ]);

  it('命中本页包含选区的那一段', () => {
    const hit = matchAnchorForSelection(byPage, 4, '就是该点切线的斜率');
    expect(hit.anchorId).toBe('p4-a');
    expect(hit.ratio).toBe(1);
  });

  it('本页有多个候选时取最长的那个（最长即最具体）', () => {
    const hit = matchAnchorForSelection(byPage, 4, '切线斜率');
    // 两段都包含「切线斜率」，取更长的 p4-b
    expect(hit.anchorId).toBe('p4-b');
  });

  it('选区跨页时看邻页', () => {
    const hit = matchAnchorForSelection(byPage, 6, '极限是微积分中第一个重要的工具');
    expect(hit.anchorId).toBe('p5-a');
  });

  it('本页与邻页都有时优先本页', () => {
    const two = pageAnchorsOf([
      plainPara(4, 'here', '切线斜率'),
      plainPara(5, 'there', '切线斜率的几何意义与求法'),
    ]);
    expect(matchAnchorForSelection(two, 4, '切线斜率').anchorId).toBe('here');
  });

  it('选区只有两三个字时不猜（太短，可能哪里都有）', () => {
    expect(matchAnchorForSelection(byPage, 4, '导数').anchorId).toBe('');
  });

  it('完全对不上时给空锚点，而不是硬塞一个', () => {
    const hit = matchAnchorForSelection(byPage, 4, '这段话与教材里的任何一段都无关');
    expect(hit.anchorId).toBe('');
  });

  it('阈值就是常量本身：选区大部分落在段内才认', () => {
    const byPageOne = pageAnchorsOf([plainPara(1, 'a', '甲乙丙丁戊己庚辛壬癸子丑寅卯')]);
    // 选区被完整包含 → 1.0，认
    expect(matchAnchorForSelection(byPageOne, 1, '甲乙丙丁戊己庚辛壬癸').anchorId).toBe('a');
    // 选区只有一半落在段内（4/8 = 0.5 < 0.6）→ 不认
    const half = '甲乙丙丁XXXX';
    expect(overlapRatio('甲乙丙丁戊己庚辛壬癸子丑寅卯', half)).toBeLessThan(MIN_MATCH_RATIO);
    expect(matchAnchorForSelection(byPageOne, 1, half).anchorId).toBe('');
  });

  it('归一化后再比：选区里的空格与全角标点不影响命中', () => {
    const hit = matchAnchorForSelection(byPage, 4, '函数在某点的导数 ，就是该点切线的斜率');
    expect(hit.anchorId).toBe('p4-a');
  });
});

describe('pdfPageOfAnchor', () => {
  it('锚点在几页就返回几页', () => {
    const byPage = pageAnchorsOf([plainPara(2, 'a', 'x'), plainPara(7, 'b', 'y')]);
    expect(pdfPageOfAnchor(byPage, 'b')).toBe(7);
  });

  it('找不到（笔记锚点已被重新解析换了 id）返回 0', () => {
    const byPage = pageAnchorsOf([plainPara(2, 'a', 'x')]);
    expect(pdfPageOfAnchor(byPage, 'gone')).toBe(0);
    expect(pdfPageOfAnchor(byPage, '')).toBe(0);
  });
});
