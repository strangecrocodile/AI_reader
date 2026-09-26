import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import App from '../App.jsx';
import { api } from '../services/api.js';
import { studyContents } from '../data/books.js';
import { BookProvider } from '../state/BookContext.jsx';
import { ToastProvider } from '../state/ToastContext.jsx';

/**
 * 「这一章没有内容」与「加载失败」必须分开。
 *
 * 以前 `fetchStudyContent` 把任何异常都吞成 null，页面于是只剩一种反应：显示
 * 「本章内容尚未准备」，而那句占位文案当时还写死了「演示数据目前只包含《高等数学》
 * 第二章 2.1 导数的概念」。后端 5xx 或断网时，一个导入医学教材的用户会看到这句话，
 * 以为自己的书根本没进去，而且页面上**没有任何重试入口**——只能自己刷新浏览器。
 *
 * 判据：失败时给可重试的错误态，并且**不出**「尚未准备」；真的没内容时才出占位页。
 */

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

function renderApp(initialEntries) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <BookProvider>
        <ToastProvider>
          <App />
        </ToastProvider>
      </BookProvider>
    </MemoryRouter>,
  );
}

const WITH_CONTENT = ['/study/calc7/ch2'];
const NOT_READY = '本章内容尚未准备';
const LOAD_FAILED = '本章内容没能加载出来';

describe('学习页的加载失败与空内容', () => {
  it('加载失败时给出可重试的错误态，而不是说「本章内容尚未准备」', async () => {
    vi.spyOn(api, 'fetchStudyContent').mockRejectedValue(new Error('API 500: /chapters/ch2'));

    renderApp(WITH_CONTENT);

    expect(await screen.findByText(LOAD_FAILED)).toBeInTheDocument();
    expect(screen.queryByText(NOT_READY)).toBeNull();
    // 错误信息要能看到，用户/我们才能判断是后端炸了还是地址配错了
    expect(screen.getByText(/API 500: \/chapters\/ch2/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument();
  });

  it('点「重试」会重新请求，成功后正常进入阅读页', async () => {
    const fetchStudyContent = vi
      .spyOn(api, 'fetchStudyContent')
      .mockRejectedValueOnce(new Error('API 503: /chapters/ch2'))
      .mockResolvedValueOnce(structuredClone(studyContents.calc7.ch2));

    const user = userEvent.setup();
    renderApp(WITH_CONTENT);
    await screen.findByText(LOAD_FAILED);

    await user.click(screen.getByRole('button', { name: '重试' }));

    expect(await screen.findByTestId('paper')).toBeInTheDocument();
    expect(fetchStudyContent).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(LOAD_FAILED)).toBeNull();
  });

  it('后端说这一章不存在（null）时仍然是占位页，不是错误态', async () => {
    vi.spyOn(api, 'fetchStudyContent').mockResolvedValue(null);

    renderApp(WITH_CONTENT);

    expect(await screen.findByText(NOT_READY)).toBeInTheDocument();
    // 空内容不该给「重试」——重试一百次也还是没有
    expect(screen.queryByText(LOAD_FAILED)).toBeNull();
    expect(screen.queryByRole('button', { name: '重试' })).toBeNull();
  });

  it('占位页不再提「演示数据」和某一章的标题', async () => {
    // 这是给「你的教材这一章没解析出正文」用的提示，不是演示数据的说明
    vi.spyOn(api, 'fetchStudyContent').mockResolvedValue(null);

    renderApp(WITH_CONTENT);
    await screen.findByText(NOT_READY);

    expect(screen.queryByText(/演示数据/)).toBeNull();
    expect(screen.queryByText(/2\.1 导数的概念/)).toBeNull();
  });
});
