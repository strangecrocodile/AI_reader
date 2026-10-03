import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

/**
 * 原版 PDF 阅读面。
 *
 * jsdom 里没有 canvas、没有真正的 PDF 渲染，所以 `pdfjs-dist` 整个被替换成假实现：
 * 这里测的**不是 pdf.js 画得对不对**（那是它的事），而是我们自己那层接线——
 * 页码怎么换算、选区怎么认回锚点、按页怎么上报已读、打不开时怎么退回结构化视图。
 *
 * 假文档刻意做成「第 3 页起是扫描件（没有文字层）」，好把扫描件提示也一并盖住。
 */

const PAGES = 4;

class FakeTextLayer {
  constructor({ textContentSource, container }) {
    this.container = container;
    this.items = textContentSource?.items ?? [];
  }

  async render() {
    for (const item of this.items) {
      const span = document.createElement('span');
      span.textContent = item.str;
      this.container.appendChild(span);
    }
  }

  cancel() {}
}

function fakeDoc() {
  return {
    numPages: PAGES,
    destroyed: false,
    async getPage(page) {
      return {
        getViewport: ({ scale }) => ({ width: 600 * scale, height: 800 * scale }),
        render: () => ({ promise: Promise.resolve() }),
        async getTextContent() {
          // 第 3 页是扫描件：没有任何文字
          if (page === 3) return { items: [] };
          return { items: [{ str: `原书第 ${page} 页的一行文字` }] };
        },
      };
    },
    destroy() {
      this.destroyed = true;
    },
  };
}

let loadRejects = null;
const destroySpy = vi.fn();

// 走的是 legacy 构建（老浏览器兼容，理由见 utils/pdfAssets.js）
vi.mock('pdfjs-dist/legacy/build/pdf.mjs', () => ({
  GlobalWorkerOptions: {},
  getDocument: () => {
    const task = {
      promise: loadRejects
        ? Promise.reject(loadRejects)
        : Promise.resolve(fakeDoc()),
      destroy: destroySpy,
    };
    return task;
  },
  TextLayer: FakeTextLayer,
}));

vi.mock('pdfjs-dist/legacy/build/pdf.worker.min.mjs?url', () => ({
  default: '/pdfjs/pdf.worker.min.mjs',
}));

const { default: PdfReader } = await import('../components/PdfReader.jsx');
const { pageAnchorsOf } = await import('../utils/anchorPage.js');

/** 一章 4 页，第 1、2 页有正文段落（锚点），第 3 页是扫描件 */
const CONTENT = {
  bookId: 'b1',
  chapterId: 'b1-ch2',
  page: 1,
  pageEnd: 4,
  heading: '第2章 导数与微分',
  sourceFormat: 'pdf',
  hasSource: true,
  pageOffset: 0,
  paragraphs: [
    { type: 'p', page: 1, segs: [{ t: 'src', id: 'b1-s2-1', v: '函数在某点的导数，就是该点切线的斜率。' }] },
    { type: 'p', page: 2, segs: [{ t: 'src', id: 'b1-s2-2', v: '极限描述了无限逼近的过程，是微积分的第一件工具。' }] },
  ],
};

/** 装一个能手动驱动的 IntersectionObserver：测试要自己决定「哪几页可见」。 */
let observers = [];
class FakeObserver {
  constructor(callback, options) {
    this.callback = callback;
    this.options = options;
    this.targets = [];
    observers.push(this);
  }

  observe(node) {
    this.targets.push(node);
  }

  disconnect() {
    this.targets = [];
  }

  /** 把观察到的节点全当成「进入视口」——用来驱动页面真正开始渲染。 */
  intersectAll() {
    this.callback(
      this.targets.map((target) => ({
        target,
        isIntersecting: true,
        intersectionRatio: 1,
      })),
    );
  }

  trigger(ratios) {
    this.callback(
      this.targets.map((target) => ({
        target,
        isIntersecting: (ratios[Number(target.dataset.page)] ?? 0) > 0,
        intersectionRatio: ratios[Number(target.dataset.page)] ?? 0,
      })),
    );
  }
}

/** 页面自己的渲染观察器（带 rootMargin 的那批）。 */
const pageObservers = () => observers.filter((item) => item.options?.rootMargin);
/** 组件用来判断「当前在看哪一页」的那个（带 threshold 数组）。 */
const ratioObserver = () => observers.find((item) => Array.isArray(item.options?.threshold));

/** 让 4 页都进入渲染流程（jsdom 里没有真实视口，只能手动推进）。 */
async function renderAllPages() {
  await waitFor(() => expect(document.querySelectorAll('.pdf-page').length).toBe(PAGES));
  pageObservers().forEach((observer) => observer.intersectAll());
  // 等**span**而不是等 .textLayer 那个容器：容器在 render=true 时就有了，
  // 而里面的 span 是异步 TextLayer.render() 之后才出现的。只等容器的话，
  // 测试会在 span 还没生成时就去 selectNodeContents(null) —— 偶发失败，
  // 且失败得很快（22ms），看着像断言问题其实是个竞态。
  await waitFor(() => {
    const layer = document.querySelector('.pdf-page .textLayer');
    expect(layer?.querySelector('span')).toBeTruthy();
  });
}

beforeEach(() => {
  observers = [];
  loadRejects = null;
  destroySpy.mockClear();
  localStorage.clear();
  globalThis.IntersectionObserver = FakeObserver;
});

afterEach(() => {
  delete globalThis.IntersectionObserver;
  vi.restoreAllMocks();
});

function renderReader(props = {}) {
  return render(
    <MemoryRouter>
      <PdfReader
        book={{ id: 'b1', title: '微积分', hasSource: true, sourceFormat: 'pdf' }}
        sourceUrl="/api/books/b1/source?inline=1"
        content={CONTENT}
        onSelect={() => {}}
        onRead={() => {}}
        {...props}
      />
    </MemoryRouter>,
  );
}

describe('原版 PDF 阅读面', () => {
  it('按文档页数渲染页面，并显示真实页码', async () => {
    renderReader();

    await waitFor(() => expect(document.querySelectorAll('.pdf-page').length).toBe(PAGES));
    // 页码栏：第 1 / 4 页
    expect(screen.getByLabelText('跳转到页')).toHaveValue('1');
    expect(screen.getByText(/\/ 4 页/)).toBeInTheDocument();
  });

  it('章节页范围如实显示（教材依据里的「第 N 页」要对得上）', async () => {
    renderReader();
    expect(await screen.findByText('本章第 1–4 页')).toBeInTheDocument();
  });

  it('页码换算减掉印刷偏移：书上第 9 页要翻到 PDF 第 1 页', async () => {
    renderReader({
      content: { ...CONTENT, pageOffset: 8, page: 9, pageEnd: 12 },
    });
    expect(await screen.findByText('本章第 9–12 页')).toBeInTheDocument();
  });

  it('选区落在某一段里时，回填那个锚点', async () => {
    const onSelect = vi.fn();
    renderReader({ onSelect });

    await renderAllPages();
    const page = document.querySelector('[data-page="1"]');
    const span = page.querySelector('.textLayer span');
    const range = document.createRange();
    range.selectNodeContents(span);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    fireEvent.mouseUp(page);

    expect(onSelect).toHaveBeenCalledTimes(1);
    const [text, meta] = onSelect.mock.calls[0];
    expect(text).toContain('原书第 1 页');
    expect(meta.page).toBe(1);
    // 文字层里的字与段落不同，认不出来时给空串——但提问这条路仍然可用
    expect(meta.anchorId).toBe('');
  });

  it('选区与段落文本一致时认回锚点', async () => {
    const onSelect = vi.fn();
    renderReader({ onSelect });

    await renderAllPages();
    const page = document.querySelector('[data-page="1"]');
    const span = page.querySelector('.textLayer span');
    // 换成与段落一模一样的文字：这才是「选中原文」的正常情况
    span.textContent = '函数在某点的导数，就是该点切线的斜率。';
    const range = document.createRange();
    range.selectNodeContents(span);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    fireEvent.mouseUp(page);

    expect(onSelect.mock.calls[0][1].anchorId).toBe('b1-s2-1');
  });

  it('按页上报已读：可见页里的锚点各报一次', async () => {
    const onRead = vi.fn();
    renderReader({ onRead });
    await renderAllPages();

    // 第 1 页可见 → 上报它的锚点
    ratioObserver().trigger({ 1: 0.9 });
    await waitFor(() => expect(onRead).toHaveBeenCalledWith(['b1-s2-1']));

    // 同一页再触发一次不重复上报（反复滚动不该重复计分）
    ratioObserver().trigger({ 1: 0.9 });
    expect(onRead).toHaveBeenCalledTimes(1);

    // 翻到第 2 页 → 报第 2 页的锚点
    ratioObserver().trigger({ 2: 0.8 });
    await waitFor(() => expect(onRead).toHaveBeenCalledWith(['b1-s2-2']));
  });

  it('通过 focusId 定位到锚点所在的那一页', async () => {
    renderReader({ focusId: 'b1-s2-2' });
    await renderAllPages();

    // b1-s2-2 在第 2 页：页码框应跳到 2（滚动本身在 jsdom 里是空实现）
    await waitFor(() => expect(screen.getByLabelText('跳转到页')).toHaveValue('2'));
  });

  it('当前页是扫描件（没有文字层）时如实提示，而不是让人以为选不中是自己手笨', async () => {
    renderReader();
    await renderAllPages();

    ratioObserver().trigger({ 3: 0.9 });

    expect(await screen.findByText(/第 3 页是扫描图片/)).toBeInTheDocument();
    expect(screen.getByText(/切到\s*「结构化」视图/)).toBeInTheDocument();
  });

  it('打不开时交给上层回退，并给一句可读的说明', async () => {
    const onError = vi.fn();
    const error = new Error('文件不是有效的 PDF');
    error.name = 'InvalidPDFException';
    loadRejects = error;

    renderReader({ onError });

    await waitFor(() => expect(onError).toHaveBeenCalledWith('文件不是有效的 PDF'));
    expect(await screen.findByText(/原版 PDF 打不开/)).toBeInTheDocument();
  });

  it('本页有笔记时在页角点一个数（位置不可靠，所以不画在原文上）', async () => {
    renderReader({ notedAnchorIds: new Set(['b1-s2-2']) });
    await waitFor(() => expect(document.querySelectorAll('.pdf-page').length).toBe(PAGES));

    expect(screen.getByTitle('本页有 1 条笔记')).toBeInTheDocument();
  });

  it('分页模式下只显示当前页', async () => {
    renderReader({ viewMode: 'page' });
    await waitFor(() => expect(document.querySelectorAll('.pdf-page').length).toBe(PAGES));

    expect(document.querySelector('.pdf-pages')).toHaveClass('pdf-single');
    expect(document.querySelector('[data-page="1"]')).toHaveClass('current');
  });

  it('缩放按钮改比例并记在本地', async () => {
    renderReader();
    await waitFor(() => expect(screen.getByText('100%')).toBeInTheDocument());

    fireEvent.click(screen.getByLabelText('放大'));

    expect(screen.getByText('125%')).toBeInTheDocument();
    expect(localStorage.getItem('ai_reader.pdfZoom')).toBe('1.25');
  });

  it('卸载时销毁文档（否则来回切章节会一直攒着解析好的 PDF）', async () => {
    const { unmount } = renderReader();
    await waitFor(() => expect(document.querySelectorAll('.pdf-page').length).toBe(PAGES));

    unmount();

    expect(destroySpy).toHaveBeenCalled();
  });
});

describe('anchorPage 与渲染面的约定', () => {
  it('页码归组与阅读面用的是同一份段落数据', () => {
    const byPage = pageAnchorsOf(CONTENT.paragraphs, 0);
    expect(byPage.get(1)[0].anchorId).toBe('b1-s2-1');
    expect(byPage.get(2)[0].anchorId).toBe('b1-s2-2');
  });
});
