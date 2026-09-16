import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import App from '../App.jsx';
import { api } from '../services/api.js';
import { books as mockBooks } from '../data/books.js';
import { BookProvider } from '../state/BookContext.jsx';
import { ToastProvider } from '../state/ToastContext.jsx';

/**
 * 删除教材的交互测试。
 *
 * `window.confirm` 在 jsdom 里**没有实现**（调用只会在控制台报一个 jsdomError
 * 然后返回 undefined，也就是永远「取消」），所以每个用例都得自己 stub。
 */

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderApp() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <BookProvider>
        <ToastProvider>
          <App />
        </ToastProvider>
      </BookProvider>
    </MemoryRouter>,
  );
}

async function openModal(user) {
  await user.click(screen.getByRole('button', { name: /更换教材/ }));
}

/** 让 `fetchBooks` 像真后端一样：删掉之后，下一轮列表里就没有这本书了。 */
function serveShelf({ removeOnDelete = [] } = {}) {
  const gone = new Set();
  const fetchBooks = vi
    .spyOn(api, 'fetchBooks')
    .mockImplementation(async () => mockBooks.filter((b) => !gone.has(b.id)));
  const deleteBook = vi
    .spyOn(api, 'deleteBook')
    .mockImplementation(async (id) => {
      if (removeOnDelete.includes(id)) gone.add(id);
    });
  return { fetchBooks, deleteBook, gone };
}

describe('删除教材', () => {
  it('确认框点取消：一个请求都不发，教材还在', async () => {
    const { fetchBooks, deleteBook } = serveShelf();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);

    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    await openModal(user);
    const callsBefore = fetchBooks.mock.calls.length;

    await user.click(screen.getByRole('button', { name: '删除《线性代数》' }));

    expect(confirm).toHaveBeenCalled();
    expect(deleteBook).not.toHaveBeenCalled();
    // 连列表都不该重读——没删成功就没有刷新的理由
    expect(fetchBooks.mock.calls.length).toBe(callsBefore);
    expect(screen.getByTestId('book-choice-linalg6')).toBeInTheDocument();
  });

  it('确认文案要说清代价：章节数、不可恢复、扫描件得重新识别', async () => {
    serveShelf();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);

    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    await openModal(user);
    await user.click(screen.getByRole('button', { name: '删除《线性代数》' }));

    const message = confirm.mock.calls[0][0];
    expect(message).toContain('线性代数');
    expect(message).toContain('无法恢复');
    expect(message).toContain('个章节');
    // 扫描件是唯一「删了要再等几十分钟」的东西，必须提前说
    expect(message).toContain('重新识别');
  });

  it('确认后调删除接口、重读列表并提示', async () => {
    const { deleteBook } = serveShelf({ removeOnDelete: ['linalg6'] });
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    await openModal(user);

    await user.click(screen.getByRole('button', { name: '删除《线性代数》' }));

    expect(deleteBook).toHaveBeenCalledWith('linalg6');
    expect(await screen.findByText('已删除《线性代数 · 第六版》')).toBeInTheDocument();
    // 列表以服务端为准，不能只本地过滤掉——否则删一半失败时会显示一本其实还在的书
    await waitFor(() => expect(screen.queryByTestId('book-choice-linalg6')).toBeNull());
  });

  it('删掉的是当前教材时，切到列表里的下一本', async () => {
    // 初始当前教材是「高等数学」（calc7），它被删掉之后应该落到线性代数上
    const { gone } = serveShelf({ removeOnDelete: ['calc7'] });
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    expect(screen.getByTestId('book-cover')).toHaveTextContent('高等数学');
    await openModal(user);

    await user.click(screen.getByRole('button', { name: '删除《高等数学》' }));

    await waitFor(() => expect(gone.has('calc7')).toBe(true));
    await waitFor(() => expect(screen.getByTestId('book-cover')).toHaveTextContent('线性代数'));
    // localStorage 里的死 id 也要换掉，否则下次进来还会先指向一本不存在的书
    expect(localStorage.getItem('ai_reader.currentBookId')).toBe('linalg6');
  });

  it('删光之后主页回到「还没有教材」，而不是卡在空壳上', async () => {
    serveShelf({ removeOnDelete: mockBooks.map((b) => b.id) });
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    await openModal(user);

    for (const book of mockBooks) {
      await user.click(screen.getByRole('button', { name: `删除《${book.title}》` }));
      await waitFor(() => expect(screen.queryByTestId(`book-choice-${book.id}`)).toBeNull());
    }

    expect(await screen.findByText('还没有教材')).toBeInTheDocument();
  });

  it('删除失败时如实报错，教材留在列表里', async () => {
    const fetchBooks = vi.spyOn(api, 'fetchBooks').mockResolvedValue(mockBooks);
    vi.spyOn(api, 'deleteBook').mockRejectedValue(new Error('教材不存在'));
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    await openModal(user);
    const callsBefore = fetchBooks.mock.calls.length;

    await user.click(screen.getByRole('button', { name: '删除《线性代数》' }));

    expect(await screen.findByText('教材不存在')).toBeInTheDocument();
    expect(screen.getByTestId('book-choice-linalg6')).toBeInTheDocument();
    // 失败就不刷新列表（也就不会被「已删除」的假象骗到）
    expect(fetchBooks.mock.calls.length).toBe(callsBefore);
  });
});

describe('教材列表自愈', () => {
  it('打开弹窗时重读服务端——后台完成的入库不该等用户自己刷新页面', async () => {
    // 第一次拉到的列表里没有「新入库教材」，第二次才有：模拟识别在弹窗关闭期间完成
    const late = { ...mockBooks[0], id: 'late-book', title: '后来才入库的教材' };
    const fetchBooks = vi
      .spyOn(api, 'fetchBooks')
      .mockResolvedValueOnce(mockBooks)
      .mockResolvedValue([...mockBooks, late]);

    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    expect(screen.queryByTestId('book-choice-late-book')).toBeNull();

    await openModal(user);

    // 这正是用户遇到的问题：书在库里，界面却看不见。现在一开弹窗就自己长出来了。
    expect(await screen.findByTestId('book-choice-late-book')).toBeInTheDocument();
    expect(fetchBooks).toHaveBeenCalledTimes(2);
  });
});
