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
 * 「调整计划」必须真的重算。
 *
 * 这个按钮过去只弹一句「已为你重新规划本周进度」，一次请求都不发——用户点了之后
 * 计划没有任何变化（因为它本来就没被重算过），比没有这个按钮更糟：它让人以为
 * AI 规划不管用。这里的判据是**真发生了两件事**：调了重算接口，并且重读了列表
 * （展示用的 plan 是后端序列化后的形态，不重读就看不到新的）。
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

const ADJUST = { name: '调整计划' };

describe('调整计划', () => {
  it('点击后调重算接口、重读列表，并提示成功', async () => {
    const regeneratePlan = vi.spyOn(api, 'regeneratePlan').mockResolvedValue({ items: [] });
    const fetchBooks = vi.spyOn(api, 'fetchBooks').mockImplementation(async () => mockBooks);
    const user = userEvent.setup();

    renderApp();
    await screen.findByText('正在学习的教材');
    expect(fetchBooks).toHaveBeenCalledTimes(1); // 挂载时那一次

    await user.click(screen.getByRole('button', ADJUST));

    await waitFor(() => expect(regeneratePlan).toHaveBeenCalledWith(mockBooks[0].id));
    // 不重读列表的话，用户看到的目标与单元数还是旧的——等于白点
    await waitFor(() => expect(fetchBooks).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('已重新规划本周进度')).toBeInTheDocument();
  });

  it('重算期间按钮禁用并换文案，避免连点堆出多次请求', async () => {
    let finish;
    vi.spyOn(api, 'regeneratePlan').mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    vi.spyOn(api, 'fetchBooks').mockImplementation(async () => mockBooks);
    const user = userEvent.setup();

    renderApp();
    await screen.findByText('正在学习的教材');
    await user.click(screen.getByRole('button', ADJUST));

    const pending = await screen.findByRole('button', { name: '正在重新规划…' });
    expect(pending).toBeDisabled();

    finish({ items: [] });
    await waitFor(() => expect(screen.getByRole('button', ADJUST)).toBeEnabled());
  });

  it('重算失败时把原因说出来，按钮恢复可用', async () => {
    vi.spyOn(api, 'regeneratePlan').mockRejectedValue(new Error('API 500: /plan'));
    vi.spyOn(api, 'fetchBooks').mockImplementation(async () => mockBooks);
    const user = userEvent.setup();

    renderApp();
    await screen.findByText('正在学习的教材');
    await user.click(screen.getByRole('button', ADJUST));

    expect(await screen.findByText('API 500: /plan')).toBeInTheDocument();
    expect(screen.getByRole('button', ADJUST)).toBeEnabled();
  });

  it('演示模式（未连后端）如实说做不到，而不是假装重算过了', async () => {
    // 不 mock regeneratePlan：apiBase 为空时它自己会以「演示模式」为由拒绝
    const user = userEvent.setup();

    renderApp();
    await screen.findByText('正在学习的教材');
    await user.click(screen.getByRole('button', ADJUST));

    expect(await screen.findByText(/演示模式不支持重新规划/)).toBeInTheDocument();
  });
});
