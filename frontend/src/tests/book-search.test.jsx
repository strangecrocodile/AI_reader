import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import App from '../App.jsx';
import { api } from '../services/api.js';
import { BookProvider } from '../state/BookContext.jsx';
import { ToastProvider } from '../state/ToastContext.jsx';

/**
 * 全书搜索。
 *
 * 在这个功能之前，「我记得书里讲过 X，但忘了在哪一章」只能去右栏当一个问题提，
 * 再从回答的「教材依据」里倒推位置——定位被做成了提问的副产品。这里要保证的是
 * 它是一条**独立**的路：输入就出结果，点一下就跳过去并高亮。
 */

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

function renderApp() {
  return render(
    <MemoryRouter initialEntries={['/study/calc7/ch2']}>
      <BookProvider>
        <ToastProvider>
          <App />
        </ToastProvider>
      </BookProvider>
    </MemoryRouter>,
  );
}

const HITS = [
  {
    anchorId: 'source-rate',
    chapterId: 'ch2',
    chapterTitle: '导数与微分',
    page: 47,
    text: '一个量相对于另一个量的变化率',
    kind: 'p',
    score: 3.2,
  },
  {
    anchorId: 'source-other',
    chapterId: 'ch1',
    chapterTitle: '函数与极限',
    page: 12,
    text: '极限描述的是趋势，而不是某一个具体取值。',
    kind: 'p',
    score: 1.1,
  },
];

async function openSearch(user) {
  await screen.findByTestId('paper');
  await user.click(screen.getByTestId('search-toggle'));
  return screen.findByLabelText('搜索整本教材');
}

describe('全书搜索', () => {
  it('输入关键词后列出命中，标明章节与页码', async () => {
    const search = vi.spyOn(api, 'searchBook').mockResolvedValue({ query: '变化率', total: 2, hits: HITS });
    const user = userEvent.setup();

    renderApp();
    const input = await openSearch(user);
    await user.type(input, '变化率');

    await waitFor(() => expect(search).toHaveBeenCalledWith('calc7', '变化率'));
    const hit = await screen.findByTestId('search-hit-source-rate');
    expect(hit).toHaveTextContent('导数与微分');
    expect(hit).toHaveTextContent('第 47 页');
  });

  it('跨章命中会被标出来——点下去是换章，不是在本章滚动', async () => {
    vi.spyOn(api, 'searchBook').mockResolvedValue({ query: '极限', total: 2, hits: HITS });
    const user = userEvent.setup();

    renderApp();
    const input = await openSearch(user);
    await user.type(input, '极限');

    const cross = await screen.findByTestId('search-hit-source-other');
    expect(cross).toHaveTextContent('其他章节');
    // 同章的那条不该被标成跨章，否则提示就没意义了
    expect(screen.getByTestId('search-hit-source-rate')).not.toHaveTextContent('其他章节');
  });

  it('点同章结果会在本章定位并高亮，不换章', async () => {
    vi.spyOn(api, 'searchBook').mockResolvedValue({ query: '变化率', total: 2, hits: HITS });
    const user = userEvent.setup();

    renderApp();
    const input = await openSearch(user);
    await user.type(input, '变化率');
    await user.click(await screen.findByTestId('search-hit-source-rate'));

    // 定位提示带页码，用户能立刻对照原文核对
    expect(await screen.findByText(/教材依据 · 第 47 页/)).toBeInTheDocument();
    expect(screen.getByTestId('paper')).toBeInTheDocument(); // 还在本章
  });

  it('点跨章结果真的换章，而不是在本章里空滚一下', async () => {
    vi.spyOn(api, 'searchBook').mockResolvedValue({ query: '极限', total: 2, hits: HITS });
    const user = userEvent.setup();

    renderApp();
    const input = await openSearch(user);
    await user.type(input, '极限');
    await user.click(await screen.findByTestId('search-hit-source-other'));

    // ch2 有正文、ch1 没有，所以「阅读区消失」就证明真的换过去了
    await waitFor(() => expect(screen.queryByTestId('paper')).toBeNull());
    // 搜索面板顺手收起来，不挡着用户看跳过去的那段原文
    expect(screen.queryByTestId('book-search')).toBeNull();
  });

  it('搜不到时明说没找到，而不是留一片空白', async () => {
    vi.spyOn(api, 'searchBook').mockResolvedValue({ query: '量子', total: 0, hits: [] });
    const user = userEvent.setup();

    renderApp();
    const input = await openSearch(user);
    await user.type(input, '量子');

    expect(await screen.findByText(/教材里没有找到「量子」/)).toBeInTheDocument();
  });

  it('搜索失败时说失败，不能伪装成「没有结果」', async () => {
    vi.spyOn(api, 'searchBook').mockRejectedValue(new Error('API 500: /search'));
    const user = userEvent.setup();

    renderApp();
    const input = await openSearch(user);
    await user.type(input, '梯度');

    expect(await screen.findByText(/搜索没成功/)).toBeInTheDocument();
    expect(screen.queryByText(/没有找到/)).toBeNull();
  });

  it('打字过程中只发一次请求，不是每敲一个字都发', async () => {
    const search = vi.spyOn(api, 'searchBook').mockResolvedValue({ query: '梯度', total: 0, hits: [] });
    const user = userEvent.setup();

    renderApp();
    const input = await openSearch(user);
    await user.type(input, '梯度消失');

    await waitFor(() => expect(search).toHaveBeenCalled());
    expect(search).toHaveBeenCalledTimes(1);
    expect(search).toHaveBeenCalledWith('calc7', '梯度消失');
  });

  it('清空输入后不请求，也不留下上一次的结果', async () => {
    const search = vi.spyOn(api, 'searchBook').mockResolvedValue({ query: 'x', total: 2, hits: HITS });
    const user = userEvent.setup();

    renderApp();
    const input = await openSearch(user);
    await user.type(input, '变化率');
    await screen.findByTestId('search-hit-source-rate');

    await user.clear(input);

    await waitFor(() => expect(screen.queryByTestId('search-results')).toBeNull());
    expect(search).toHaveBeenCalledTimes(1);
  });
});
