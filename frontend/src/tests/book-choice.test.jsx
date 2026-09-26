import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import App from '../App.jsx';
import { api } from '../services/api.js';
import { books as mockBooks } from '../data/books.js';
import { BookProvider } from '../state/BookContext.jsx';
import { ToastProvider } from '../state/ToastContext.jsx';

/**
 * 「更换教材」弹窗里每一行的展示。
 *
 * 这里的重点是**不要编造**：列表是用户确认「我导入了什么」的地方，一行里多一句
 * 假话，用户就得先去别处核对才能确认自己的书进来了。
 */

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
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

/** 一本「真后端导入的书」：`edition` 是空串（后端不从文档推断版次）。 */
function importedBook({ id = 'pdf1', title = '神经网络与深度学习', edition = '' } = {}) {
  return { ...mockBooks[0], id, title, edition };
}

function serveShelf(shelf) {
  vi.spyOn(api, 'fetchBooks').mockImplementation(async () => shelf);
}

async function openModal(user) {
  await user.click(screen.getByRole('button', { name: /更换教材/ }));
}

describe('教材选择行', () => {
  it('没有版次时只显示书名，不编一个「第 3 版」出来', async () => {
    serveShelf([importedBook()]);
    const user = userEvent.setup();

    renderApp();
    await screen.findByText('正在学习的教材');
    await openModal(user);

    const row = screen.getByTestId('book-choice-pdf1');
    expect(row).toHaveTextContent('神经网络与深度学习');
    // 后端对所有导入教材都返回 edition: ''，所以任何「第 N 版」都是前端凭空造的
    expect(row).not.toHaveTextContent(/第\s*\d+\s*版/);
  });

  it('演示数据自带版次时照常显示——不能为了不编造就把真信息也去掉', async () => {
    serveShelf([{ ...mockBooks[1], edition: '第六版' }]);
    const user = userEvent.setup();

    renderApp();
    await screen.findByText('正在学习的教材');
    await openModal(user);

    expect(screen.getByTestId('book-choice-linalg6')).toHaveTextContent('线性代数 · 第六版');
  });

  it('书名较长时也不截断成莫名其妙的样子', async () => {
    const longTitle = 'Predictive Coding Enhances Meta-RL Under Partial Observability';
    serveShelf([importedBook({ title: longTitle })]);
    const user = userEvent.setup();

    renderApp();
    await screen.findByText('正在学习的教材');
    await openModal(user);

    expect(screen.getByTestId('book-choice-pdf1')).toHaveTextContent(longTitle);
  });
});
