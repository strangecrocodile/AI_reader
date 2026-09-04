import { describe, expect, it } from 'vitest';
import { escapeHtml, truncate } from '../utils/text.js';

describe('escapeHtml', () => {
  it('转义 HTML 特殊字符', () => {
    expect(escapeHtml('<b>&"x"</b>')).toBe('&lt;b&gt;&amp;&quot;x&quot;&lt;/b&gt;');
  });

  it('普通文本原样返回', () => {
    expect(escapeHtml('为什么一定要取极限？')).toBe('为什么一定要取极限？');
  });
});

describe('truncate', () => {
  it('短文本不截断', () => {
    expect(truncate('一行原文')).toBe('一行原文');
  });

  it('长文本截断到 34 字符并加省略号', () => {
    const long = 'x'.repeat(40);
    expect(truncate(long)).toBe('x'.repeat(34) + '…');
  });

  it('支持自定义最大长度', () => {
    expect(truncate('abcdef', 3)).toBe('abc…');
  });
});
