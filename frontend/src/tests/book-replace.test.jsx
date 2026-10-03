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
 * 「重新上传并替换本书」的交互。
 *
 * 这条路径唯一的存在理由是**保住学习记录**，所以测试盯的是两件事：
 * ① 替换前必须让用户知道「换的是内容、留的是记录」；
 * ② 替换后把「保住了什么」如实报出来（线程几条、笔记几条），
 *    而不是只说一句「成功」——用户没法核对他最在乎的那些东西还在不在。
 *
 * `window.confirm` 在 jsdom 里没有实现，所以每个用例都得自己 stub。
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

const REPLACED = {
  ...mockBooks[0],
  id: 'linalg6',
  title: '线性代数',
  replace: { chaptersAdded: 1, chaptersUpdated: 4, threadsReanchored: 2, notesReanchored: 1 },
};

/** 把「替换」这条路的后端伪装起来：请求与列表刷新。 */
function serveReplace({ ok = true } = {}) {
  const fetchBooks = vi.spyOn(api, 'fetchBooks').mockImplementation(async () => mockBooks);
  const replaceBook = vi.spyOn(api, 'replaceBook').mockImplementation(async () => {
    if (!ok) throw new Error('替换暂不支持扫描件 PDF');
    return REPLACED;
  });
  return { fetchBooks, replaceBook };
}

const FILE = () => new File(['%PDF-new'], '新版本.pdf', { type: 'application/pdf' });

/** 走的必须与用户一样的两步：先点「替换」选定这本书，再选文件。 */
async function replaceWith(user, file = FILE(), label = '替换《线性代数》的内容') {
  await user.click(screen.getByRole('button', { name: label }));
  await user.upload(screen.getByLabelText('选择用于替换的教材文件'), file);
}

describe('替换教材', () => {
  it('替换与删除是两个按钮：一个保住记录，一个全部清零', async () => {
    serveReplace();
    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    await openModal(user);

    expect(screen.getByRole('button', { name: '替换《线性代数》的内容' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '删除《线性代数》' })).toBeInTheDocument();
  });

  it('确认框点取消：一个请求都不发', async () => {
    const { replaceBook } = serveReplace();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    await openModal(user);

    await replaceWith(user);

    expect(confirm).toHaveBeenCalled();
    expect(replaceBook).not.toHaveBeenCalled();
  });

  it('确认文案说清「内容换掉、记录留下」，别让人以为会清空', async () => {
    serveReplace();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    await openModal(user);

    await replaceWith(user);

    const text = confirm.mock.calls[0][0];
    expect(text).toContain('替换');
    expect(text).toContain('学习进度');
    expect(text).toContain('保留');
  });

  it('替换成功后如实报告保住了什么，并重读列表', async () => {
    const { replaceBook, fetchBooks } = serveReplace();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    await openModal(user);
    const readsBefore = fetchBooks.mock.calls.length;

    await replaceWith(user);

    await waitFor(() => expect(replaceBook).toHaveBeenCalledWith('linalg6', expect.any(File)));
    expect(fetchBooks.mock.calls.length).toBeGreaterThan(readsBefore);
    // 「保住了多少」要能被核对，而不是一个笼统的「成功」
    expect(await screen.findByText(/保留线程 2 条、笔记 1 条/)).toBeInTheDocument();
    expect(screen.getByText(/新增 1 章/)).toBeInTheDocument();
  });

  it('替换失败时把后端的原因带出来，而不是只说失败', async () => {
    serveReplace({ ok: false });
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    await openModal(user);

    await replaceWith(user);

    expect(await screen.findByText('替换暂不支持扫描件 PDF')).toBeInTheDocument();
  });

  it('没有留存原文件的老书会提示「替换即可看原版」', async () => {
    vi.spyOn(api, 'fetchBooks').mockImplementation(async () =>
      mockBooks.map((book, index) => (index === 0 ? { ...book, hasSource: false } : book)),
    );
    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    await openModal(user);

    expect(screen.getByText(/原文件未留存/)).toBeInTheDocument();
    expect(screen.getByText(/用「替换」重传即可看原版/)).toBeInTheDocument();
  });

  it('演示模式（没有后端）不会假装能替换', async () => {
    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    await openModal(user);
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    await replaceWith(user);

    expect(await screen.findByText(/演示模式不支持替换教材/)).toBeInTheDocument();
  });
});
