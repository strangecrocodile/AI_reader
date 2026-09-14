import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import SegmentText, { runClassName } from '../components/SegmentText.jsx';

describe('runClassName', () => {
  it('语义 token 映射成 class 名', () => {
    expect(runClassName(['b'])).toBe('rt-b');
    expect(runClassName(['i', 'sup'])).toBe('rt-i rt-sup');
    expect(runClassName(['lg'])).toBe('rt-lg');
    expect(runClassName(['sub'])).toBe('rt-sub');
    expect(runClassName(['sm'])).toBe('rt-sm');
  });

  it('未知 token 被忽略，不产生怪样式', () => {
    expect(runClassName(['b', 'SourceHanSerifCN'])).toBe('rt-b');
    expect(runClassName([])).toBe('');
    expect(runClassName(undefined)).toBe('');
  });
});

describe('SegmentText', () => {
  it('保留老的 text / b / i 片段渲染', () => {
    render(
      <SegmentText
        segs={[
          { t: 'text', v: '普通 ' },
          { t: 'b', v: '加粗' },
          { t: 'i', v: '斜体' },
        ]}
      />,
    );

    expect(screen.getByText('普通')).toBeInTheDocument();
    expect(screen.getByText('加粗').tagName).toBe('B');
    expect(screen.getByText('斜体').tagName).toBe('I');
  });

  it('run 片段按 style 渲染成带 class 的行内元素', () => {
    const { container } = render(
      <SegmentText
        segs={[
          { t: 'run', v: '导数', style: ['b'] },
          { t: 'run', v: 'Δx→0', style: ['sub'] },
          { t: 'run', v: '普通字', style: [] },
        ]}
      />,
    );

    expect(container.querySelector('.rt-b')).toHaveTextContent('导数');
    expect(container.querySelector('.rt-sub')).toHaveTextContent('Δx→0');
    // 没有样式时不加多余 class，避免 DOM 上出现空 class
    expect(screen.getByText('普通字').className).toBe('');
  });

  it('带子片段的锚点仍带 id 与 data-source-id（锚点定位不受影响）', () => {
    const { container } = render(
      <SegmentText
        focusId="source-limit"
        segs={[
          {
            t: 'src',
            id: 'source-limit',
            v: '',
            kind: 'definition',
            segs: [{ t: 'run', v: '比值极限存在', style: ['b'] }],
          },
        ]}
      />,
    );

    const anchor = container.querySelector('[data-source-id="source-limit"]');
    expect(anchor).not.toBeNull();
    expect(anchor.id).toBe('source-limit');
    expect(anchor.className).toContain('definition');
    expect(anchor.className).toContain('focus');
    expect(anchor).toHaveTextContent('比值极限存在');
    // 子片段也渲染了，而不是退化成纯文本
    expect(anchor.querySelector('.rt-b')).not.toBeNull();
  });

  it('无版式的锚点（老数据）仍直接渲染 v', () => {
    render(<SegmentText segs={[{ t: 'src', id: 's1', v: '一段原文', kind: 'plain' }]} />);

    expect(screen.getByText('一段原文')).toBeInTheDocument();
  });

  it('segs 缺失时不抛错', () => {
    const { container } = render(<SegmentText />);
    expect(container).toBeEmptyDOMElement();
  });
});
