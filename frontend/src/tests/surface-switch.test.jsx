import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

/**
 * 阅读面选择：默认看原版，退路要说得清楚。
 *
 * 真实的 pdf.js 在 jsdom 里跑不起来（没有 canvas），这里换成假实现——本文件测的是
 * StudyPage 的**决策**：什么时候给原版、什么时候退回结构化、退回去之后有没有把
 * 原因说出来。画得对不对是 pdf.js 的事，选哪条路是我们的产品判断。
 */

const BOOK = {
  id: 'b1',
  title: '神经网络与深度学习',
  author: '来源：用户导入',
  hasSource: true,
  sourceFormat: 'pdf',
  contentWarning: '',
  progressText: '0% 已完成',
  tag: '神经网络',
  chapters: [{ id: 'b1-ch2', num: '02', title: '第2章 机器学习基础', status: 'doing', meta: '正在学习', progressPct: 0 }],
  plan: { eyebrow: '', headline: [], sub: '共 1 个学习单元', goalLabel: '', goal: '', remaining: '' },
  cover: { series: '', lines: ['神经网络与深度学习'], formula: ['PDF', '1 章'], footer: '' },
};

const CONTENT = {
  bookId: 'b1',
  chapterId: 'b1-ch2',
  page: 16,
  pageEnd: 91,
  heading: '第2章 机器学习基础',
  intro: '第 2 章 · 机器学习基础　/　第 16 页',
  sourceFormat: 'pdf',
  hasSource: true,
  pageOffset: 0,
  paragraphs: [
    { type: 'p', page: 16, segs: [{ t: 'src', id: 'b1-s2-1', v: '机器学习是从数据中提炼规律的方法。' }] },
  ],
  knowledgePoints: [],
  outline: [],
};

class FakeTextLayer {
  constructor({ container }) {
    this.container = container;
  }

  async render() {
    const span = document.createElement('span');
    span.textContent = '机器学习是从数据中提炼规律的方法。';
    this.container.appendChild(span);
  }

  cancel() {}
}

vi.mock('pdfjs-dist', () => ({
  GlobalWorkerOptions: {},
  getDocument: () => ({
    promise: Promise.resolve({
      numPages: 1,
      destroy() {},
      async getPage() {
        return {
          getViewport: ({ scale }) => ({ width: 600 * scale, height: 800 * scale }),
          render: () => ({ promise: Promise.resolve() }),
          async getTextContent() {
            return { items: [{ str: '机器学习是从数据中提炼规律的方法。' }] };
          },
        };
      },
    }),
    destroy() {},
  }),
  TextLayer: FakeTextLayer,
}));

vi.mock('pdfjs-dist/build/pdf.worker.min.mjs?url', () => ({ default: '/pdfjs/pdf.worker.min.mjs' }));

const { default: App } = await import('../App.jsx');
const { BookProvider } = await import('../state/BookContext.jsx');
const { ToastProvider } = await import('../state/ToastContext.jsx');
const { configureApiBase } = await import('../services/api.js');

class FakeObserver {
  constructor(callback, options) {
    this.callback = callback;
    this.options = options;
    this.targets = [];
  }

  observe(node) {
    this.targets.push(node);
  }

  disconnect() {
    this.targets = [];
  }

  intersectAll() {
    this.callback(this.targets.map((target) => ({ target, isIntersecting: true, intersectionRatio: 1 })));
  }
}

let book = BOOK;

/** 章节内容里的来源信息与书架保持一致——真实后端就是这么下发的。 */
const contentOf = () => ({ ...CONTENT, hasSource: book.hasSource, sourceFormat: book.sourceFormat });

function mockFetch() {
  return vi.fn(async (url) => {
    const path = String(url).replace('http://backend.test', '');
    if (path === '/api/books') return { ok: true, status: 200, json: async () => [book] };
    if (path === '/api/books/b1') return { ok: true, status: 200, json: async () => book };
    if (path.endsWith('/chapters/b1-ch2')) return { ok: true, status: 200, json: async () => contentOf() };
    if (path.includes('/threads') || path.includes('/notes') || path.includes('/quiz')) {
      return { ok: true, status: 200, json: async () => [] };
    }
    if (path.includes('/events')) {
      return { ok: true, status: 200, json: async () => ({ mastery: 0, status: 'learning', breakdown: [], signals: {} }) };
    }
    if (path.includes('/knowledge')) {
      return { ok: true, status: 200, json: async () => ({ concepts: [], relations: [], unresolved: [], stats: {} }) };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  });
}

beforeEach(() => {
  localStorage.clear();
  book = BOOK;
  globalThis.IntersectionObserver = FakeObserver;
  configureApiBase('http://backend.test');
  vi.stubGlobal('fetch', mockFetch());
});

afterEach(() => {
  configureApiBase('');
  vi.unstubAllGlobals();
  delete globalThis.IntersectionObserver;
});

function renderStudy() {
  return render(
    <MemoryRouter initialEntries={['/study/b1/b1-ch2']}>
      <BookProvider>
        <ToastProvider>
          <App />
        </ToastProvider>
      </BookProvider>
    </MemoryRouter>,
  );
}

/** 等阅读面就绪（原版会先加载文档，结构化会先铺纸张）。 */
async function waitForReader() {
  return waitFor(() => expect(document.querySelector('.pdf-reader, .paper')).toBeTruthy(), {
    timeout: 3000,
  });
}

describe('阅读面：默认原版，退路说清楚', () => {
  it('留了原文件的书默认就用原版 PDF', async () => {
    renderStudy();
    await waitForReader();

    expect(document.querySelector('.pdf-reader')).toBeTruthy();
    expect(document.querySelector('.paper')).toBeNull();
    expect(screen.getByRole('button', { name: '原版' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('可以切回结构化视图，且这个选择会被记住', async () => {
    renderStudy();
    await waitForReader();

    fireEvent.click(screen.getByRole('button', { name: '结构化' }));

    expect(document.querySelector('.paper')).toBeTruthy();
    expect(document.querySelector('.pdf-reader')).toBeNull();
    expect(localStorage.getItem('ai_reader.surface')).toBe('text');
  });

  it('记住的选择在重新进入时生效', async () => {
    localStorage.setItem('ai_reader.surface', 'text');
    renderStudy();
    await waitForReader();

    expect(document.querySelector('.paper')).toBeTruthy();
    expect(screen.getByRole('button', { name: '结构化' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('没有留存原文件的老书：用结构化视图，并说清「重新上传就能看到原版」', async () => {
    book = { ...BOOK, hasSource: false, sourceFormat: '' };
    renderStudy();
    await waitForReader();

    expect(document.querySelector('.paper')).toBeTruthy();
    expect(screen.getByText(/没有留存原文件/)).toBeInTheDocument();
    expect(screen.getByText(/重新上传一次即可看到原版页面/)).toBeInTheDocument();
    // 原版按钮置灰：不是「点了没反应」，而是明确告诉用户这条路的条件
    expect(screen.getByRole('button', { name: '原版' })).toBeDisabled();
  });

  it('Word / 纯文本来源没有原版页面可看，如实说明而不是装作有', async () => {
    book = { ...BOOK, hasSource: true, sourceFormat: 'docx' };
    renderStudy();
    await waitForReader();

    expect(document.querySelector('.paper')).toBeTruthy();
    expect(screen.getByText(/只有 PDF 有/)).toBeInTheDocument();
  });
});
