import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Reader, { PAGE_MODE, SCROLL_MODE } from '../components/Reader.jsx';

/** 一份含段落 / 公式 / 插图 / 表格的章节内容。 */
const CONTENT = {
  bookId: 'bk1',
  chapterId: 'ch1',
  page: 12,
  heading: '2.1 导数的概念',
  intro: '第二章 · 导数与微分　/　第 12 页',
  paragraphs: [
    {
      type: 'p',
      segs: [
        {
          t: 'src',
          id: 'bk1-s1-1',
          v: '',
          kind: 'plain',
          segs: [
            { t: 'text', v: '比值 ' },
            { t: 'run', v: 'Δy / Δx', style: ['b'] },
            { t: 'text', v: ' 的极限记作 ' },
            { t: 'run', v: '0', style: ['sub'] },
            { t: 'text', v: '。' },
          ],
        },
      ],
    },
    { type: 'formula', parts: ['f′(x', { sub: '0' }, ') = lim'] },
    {
      type: 'image',
      id: 'bk1-s1-3',
      src: '/assets/bk1-p12-0.png',
      width: 200,
      height: 140,
      caption: '（第 12 页插图）',
    },
    {
      type: 'table',
      id: 'bk1-s1-4',
      header: true,
      rows: [
        ['概念', '记号'],
        ['导数', 'f′(x)'],
      ],
    },
  ],
};

function renderReader(props) {
  return render(
    <MemoryRouter>
      <Reader
        content={CONTENT}
        chapters={[{ id: 'ch1', num: '01', title: '导数的概念' }]}
        currentChapterId="ch1"
        {...props}
      />
    </MemoryRouter>,
  );
}

describe('Reader 富文本与图文渲染', () => {
  it('行内版式片段渲染成带 class 的元素，且锚点仍在最外层', () => {
    const { container } = renderReader();

    const anchor = container.querySelector('[data-source-id="bk1-s1-1"]');
    expect(anchor).not.toBeNull();
    expect(anchor.querySelector('.rt-b')).toHaveTextContent('Δy / Δx');
    expect(anchor.querySelector('.rt-sub')).toHaveTextContent('0');
    // 拼起来的可见文本与原文一致
    expect(anchor.textContent).toBe('比值 Δy / Δx 的极限记作 0。');
  });

  it('插图渲染为 figure + img 并带图注', () => {
    const { container } = renderReader();

    const figure = container.querySelector('.paper-figure');
    expect(figure).not.toBeNull();
    expect(figure.querySelector('img')).toHaveAttribute('src', '/assets/bk1-p12-0.png');
    expect(figure.querySelector('figcaption')).toHaveTextContent('（第 12 页插图）');
  });

  it('表格按行列渲染，首行用 th 当表头', () => {
    const { container } = renderReader();

    const table = container.querySelector('.paper-table table');
    expect(table).not.toBeNull();
    expect(Array.from(table.querySelectorAll('th')).map((th) => th.textContent)).toEqual([
      '概念',
      '记号',
    ]);
    expect(Array.from(table.querySelectorAll('td')).map((td) => td.textContent)).toEqual([
      '导数',
      'f′(x)',
    ]);
  });

  it('每个块都带 data-block-index，分页装箱才不会错位', () => {
    const { container } = renderReader();

    const indexes = Array.from(container.querySelectorAll('[data-block-index]')).map((node) =>
      Number(node.dataset.blockIndex),
    );
    // 四个块，编号连续且从 0 开始——漏一个后续页码会整体错位
    expect(indexes).toEqual([0, 1, 2, 3]);
  });

  it('未知类型的块退回按段落渲染，不白屏', () => {
    const content = {
      ...CONTENT,
      paragraphs: [{ type: 'future-widget', segs: [{ t: 'text', v: '将来才有的块' }] }],
    };
    render(
      <MemoryRouter>
        <Reader content={content} viewMode={SCROLL_MODE} />
      </MemoryRouter>,
    );

    expect(screen.getByText('将来才有的块')).toBeInTheDocument();
  });

  it('分页模式下插图与表格同样参与渲染', () => {
    const { container } = renderReader({ viewMode: PAGE_MODE });

    expect(container.querySelector('.paper.paginated')).not.toBeNull();
    expect(container.querySelector('.paper-figure')).not.toBeNull();
    expect(container.querySelector('.paper-table')).not.toBeNull();
    // 分页模式不该把块裁掉（段落始终挂载，只靠外层裁切 + 位移）
    expect(container.querySelectorAll('[data-block-index]').length).toBe(4);
  });

  it('插图缺 src 时只渲染图注，不产生坏图', () => {
    const content = {
      ...CONTENT,
      paragraphs: [{ type: 'image', id: 'img-1', src: '', caption: '图缺失' }],
    };
    const { container } = render(
      <MemoryRouter>
        <Reader content={content} viewMode={SCROLL_MODE} />
      </MemoryRouter>,
    );

    expect(container.querySelector('.paper-figure img')).toBeNull();
    expect(screen.getByText('图缺失')).toBeInTheDocument();
  });

  it('无 content 的段落（老数据）照旧渲染纯文本', () => {
    const content = {
      ...CONTENT,
      paragraphs: [
        { type: 'p', segs: [{ t: 'src', id: 'old-1', v: '一段没有版式的原文。', kind: 'plain' }] },
      ],
    };
    render(
      <MemoryRouter>
        <Reader content={content} viewMode={SCROLL_MODE} />
      </MemoryRouter>,
    );

    expect(screen.getByText('一段没有版式的原文。')).toBeInTheDocument();
  });
});
