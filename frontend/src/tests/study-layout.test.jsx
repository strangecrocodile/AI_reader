import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
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

describe('顶栏只放真能用的东西', () => {
  /**
   * 这里防的是一次实测出来的观感问题：顶栏右侧原本挂着一个写死的头像「zhang」，
   * 它点不动、也不指向任何东西——用户第一反应是「这个是不是坏了」，而不是「这是个占位」。
   * 一个不能用的控件比没有控件更糟，所以就删了。真做用户体系时再按需加回来。
   */
  it('顶栏里没有写死的占位头像', async () => {
    renderApp('/');
    await screen.findByText('正在学习的教材');

    const bar = screen.getByRole('banner');
    expect(bar).not.toHaveTextContent('zhang');
  });

  it('顶栏的每一项都能用：文字要么是链接，要么是标注了「即将上线」的禁用项', async () => {
    renderApp('/');
    await screen.findByText('正在学习的教材');

    const bar = screen.getByRole('banner');
    // 「学习报告」是唯一的故意禁用项，它自带 title 说明为什么点不动
    const disabled = bar.querySelectorAll('[aria-disabled="true"]');
    expect(disabled).toHaveLength(1);
    expect(disabled[0]).toHaveAttribute('title');
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

/**
 * 布局不变量（读 CSS 断言，因为 jsdom 没有排版引擎）。
 *
 * 这里钉的是一次**实测出来的**故障：右栏讲解卡片把网格行撑到 1301px，而视口只有
 * 802px，于是左栏（`height: 100%`）跟着变成 1301px，`.reader` 底部连同吸附在它底部
 * 的页码栏被推到视口下方——页码栏落在 y=1171，用 Chrome 量出来 `barVisible: false`，
 * 表现就是「只有在 80% 缩放下才能看见」。
 *
 * 这仓库里已有读文件断言的先例（`spatial-backdrop.test.jsx` 断言 three.js 不在依赖里），
 * 这条同理：它防的是「有人顺手把 grid-template-rows 删掉」。改动前请先用真浏览器量一次。
 */
describe('布局不变量', () => {
  // 直接读源文件（项目根就是 vitest 的工作目录）。`?raw` 导入在这个配置下对 CSS
  // 返回空串，所以走 fs——这类「读样式断言」的测试本来就与排版引擎无关。
  // 注释先剥掉：块注释里也会出现 `}`（比如写着 `{ overflow: auto }`），
  // 不去掉的话「取到第一个 `}`」会提前截断，断言的其实是半句话。
  const read = (name) =>
    readFileSync(join(process.cwd(), 'src/styles', name), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
  const studyCss = read('study.css');
  const pdfCss = read('pdf.css');

  /** 取某个选择器的声明块（这些选择器在各自文件里只有一个声明块）。 */
  function blockOf(selector) {
    const css = selector.startsWith('.pdf') ? pdfCss : studyCss;
    const at = css.indexOf(`${selector} {`);
    expect(at, `样式里找不到规则 ${selector}`).toBeGreaterThan(-1);
    return css.slice(at, css.indexOf('}', at));
  }

  it('网格行高由容器定死，不会被右栏内容撑开', () => {
    const block = blockOf('.study-layout');
    expect(block).toMatch(/height:\s*100%/);
    expect(block).toMatch(/grid-template-rows:\s*minmax\(0,\s*1fr\)/);
  });

  it('两栏都允许收缩（min-height: 0），否则内容高度会顶开行高', () => {
    expect(blockOf('.reader-column')).toMatch(/min-height:\s*0/);
    expect(blockOf('.coach')).toMatch(/min-height:\s*0/);
  });

  it('页码栏贴底：sticky bottom: 0，且阅读区不为它留出下内边距', () => {
    expect(blockOf('.pdf-bar')).toMatch(/position:\s*sticky/);
    expect(blockOf('.pdf-bar')).toMatch(/bottom:\s*0/);
    // `.reader` 的 78px 下内边距会限制 sticky 能贴到哪（实测卡在离底边 78px 处）
    expect(blockOf('.pdf-reader')).toMatch(/padding-bottom:\s*0/);
    expect(blockOf('.pdf-reader .pdf-pages')).toMatch(/padding-bottom:\s*78px/);
  });
});
