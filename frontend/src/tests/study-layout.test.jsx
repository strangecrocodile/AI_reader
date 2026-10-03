import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import App from '../App.jsx';
import Reader from '../components/Reader.jsx';
import { BookProvider } from '../state/BookContext.jsx';
import { ToastProvider } from '../state/ToastContext.jsx';

/**
 * 学习页的布局约定：
 *
 * 1. **读书时不显示顶部导航**——一次分神换来的是一段要重读的原文；退出学习这条路径由
 *    页面自己的「返回学习计划」承担，不是没有出口，只是不再摆在眼前。
 * 2. **页码在组件底部**——和纸质书的页脚一样。读者的眼睛在段末，页码就该在那儿。
 */

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

function renderApp(entry) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <BookProvider>
        <ToastProvider>
          <App />
        </ToastProvider>
      </BookProvider>
    </MemoryRouter>,
  );
}

describe('学习页不显示顶部导航', () => {
  it('进章节后看不到导航栏，但主页与知识地图仍有', async () => {
    const user = userEvent.setup();
    const { unmount } = renderApp('/');
    await screen.findByText('正在学习的教材');
    expect(screen.getByRole('link', { name: '知识地图' })).toBeInTheDocument();
    unmount();

    // 从主页进章节：进入之后导航消失
    renderApp('/');
    await screen.findByText('正在学习的教材');
    await user.click(screen.getByRole('button', { name: /开启今日学习|继续学习|开始学习/ }));
    await screen.findByTestId('paper');

    expect(screen.queryByRole('link', { name: '知识地图' })).toBeNull();
    expect(screen.queryByRole('link', { name: '我的学习' })).toBeNull();
  });

  it('知识地图页仍然有导航（只有学习页藏起来）', async () => {
    renderApp('/knowledge');
    await screen.findByText('把读过的内容，连成一张地图。');

    expect(screen.getByRole('link', { name: '我的学习' })).toBeInTheDocument();
  });

  it('学习页仍然有出口：返回学习计划', async () => {
    renderApp('/study/calc7/ch2');
    await screen.findByTestId('paper');

    expect(screen.getByRole('button', { name: '← 返回学习计划' })).toBeInTheDocument();
  });
});

describe('页码在组件底部', () => {
  it('结构化视图：页码是纸的最后一元素（正文之后），不再是标题上方', async () => {
    renderApp('/study/calc7/ch2');
    const paper = await screen.findByTestId('paper');

    const footer = screen.getByTestId('paper-page');
    expect(footer).toHaveTextContent('47'); // 演示数据这一章从第 47 页开始
    // DOM 顺序：页脚排在正文之后（视觉上就是页脚）
    expect(paper.lastElementChild).toBe(footer);
    const body = paper.querySelector('.paper-body');
    expect(body.compareDocumentPosition(footer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('页脚数字跟着正在读的段落走，不再是整章不变的起始页', async () => {
    // 这条防的是老毛病：页脚写死 `content.page`（整章起始页），翻完 76 页都不变
    const paragraphs = [
      { type: 'p', page: 47, segs: [{ t: 'src', id: 'a1', v: '第一页的正文。' }] },
      { type: 'p', page: 48, segs: [{ t: 'src', id: 'a2', v: '第二页的正文。' }] },
    ];
    let observer;
    globalThis.IntersectionObserver = class {
      constructor(callback) {
        this.callback = callback;
        this.targets = [];
        observer = this;
      }

      observe(node) {
        this.targets.push(node);
      }

      disconnect() {}
    };

    try {
      render(
        <MemoryRouter>
          <Reader
            content={{ page: 47, heading: '第2章 导数与微分', intro: '', paragraphs }}
            onRead={() => {}}
            onSelect={() => {}}
          />
        </MemoryRouter>,
      );

      expect(await screen.findByTestId('paper-page')).toHaveTextContent('47');

      // 第二段的锚点进入视口 → 页脚应当换成第 48 页
      const second = observer.targets.find((node) => node.dataset.sourceId === 'a2');
      observer.callback([
        { target: second, isIntersecting: true, intersectionRatio: 1 },
      ]);

      await waitFor(() => expect(screen.getByTestId('paper-page')).toHaveTextContent('48'));
    } finally {
      delete globalThis.IntersectionObserver;
    }
  });
});
