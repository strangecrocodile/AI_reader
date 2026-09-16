import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import App from '../App.jsx';
import { OCR_POLL_LIMITS, ocrPollBudget } from '../components/BookModal.jsx';
import { api } from '../services/api.js';
import { books as mockBooks } from '../data/books.js';
import { BookProvider } from '../state/BookContext.jsx';
import { ToastProvider } from '../state/ToastContext.jsx';

/**
 * 扫描件轮询的时限判定。
 *
 * 背景（真实故障）：一本 231 页的扫描件跑了 47 分 28 秒，前端 45 分钟就放弃了，
 * **比完成早 2 分半**；而且放弃时只发了一条 toast，列表没重读，于是教材明明已经
 * 入库，用户却在「选教材」里怎么也找不到。
 *
 * 时限本身是十几分钟量级，等不起，所以 `OCR_POLL_LIMITS` 是个可改对象，用例在
 * 渲染前把它压到毫秒级。（不用假时钟：`userEvent` 靠 `Date.now()` 推进，冻住会挂。）
 */
const DEFAULTS = { ...OCR_POLL_LIMITS };
const POLL_TIMEOUT = { timeout: 5000 };

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  Object.assign(OCR_POLL_LIMITS, DEFAULTS);
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

function ocrTask(overrides = {}) {
  return {
    id: 't1',
    status: 'running',
    filename: 'scan.pdf',
    title: '模式识别及MATLAB实现',
    totalPages: 300,
    donePages: 0,
    percent: 0,
    bookId: '',
    message: '',
    ...overrides,
  };
}

/** 打开弹窗并上传一个扫描件（后端回 202 + 任务）。 */
async function openAndUpload(user) {
  await user.click(screen.getByRole('button', { name: /更换教材/ }));
  const file = new File(['%PDF-scan'], 'scan.pdf', { type: 'application/pdf' });
  fireEvent.change(screen.getByLabelText('选择教材文件'), { target: { files: [file] } });
}

describe('ocrPollBudget：等待预算按页数算', () => {
  it('小书用 45 分钟下限，不因为页少就早早放弃', () => {
    expect(ocrPollBudget(5)).toBe(45 * 60 * 1000);
    expect(ocrPollBudget(50)).toBe(45 * 60 * 1000);
  });

  it('大书按 (页数 + 30) × 30 秒算——这正是上次算错的那个分母', () => {
    // 231 页实测跑了 47 分 28 秒，旧口径 45 分钟会提前放弃；新口径给 130 分钟
    expect(ocrPollBudget(231)).toBe((231 + 30) * 30 * 1000);
    expect(ocrPollBudget(231)).toBeGreaterThan(47 * 60 * 1000);
    expect(ocrPollBudget(400)).toBe((400 + 30) * 30 * 1000);
  });

  it('页数还不知道/是脏数据时不至于算出 0 或 NaN', () => {
    expect(ocrPollBudget(undefined)).toBe(45 * 60 * 1000);
    expect(ocrPollBudget(null)).toBe(45 * 60 * 1000);
    expect(ocrPollBudget('abc')).toBe(45 * 60 * 1000);
  });

  it('每页至少给到实测速度（12.3 秒/页）的两倍余量', () => {
    const measuredMsPerPage = 12.3 * 1000;
    const budgetMsPerPage = ocrPollBudget(400) / 400;
    expect(budgetMsPerPage).toBeGreaterThan(measuredMsPerPage * 2);
  });
});

describe('放弃等待时先刷列表再提示', () => {
  it('进度长时间不动判定为卡死：重读列表 + 提示里给出「刷新页面」的出路', async () => {
    OCR_POLL_LIMITS.stallMs = 1; // 一进循环就超时
    OCR_POLL_LIMITS.intervalMs = 20;
    // 第 3 次起（= 放弃时补的那次刷新）列表里才出现这本书，模拟「后台其实已经入库了」。
    // 自己数而不是读 mock.calls：sinon 是在实现体跑完之后才记这一笔的。
    const late = { ...mockBooks[0], id: 'late-book', title: '其实已经入库的教材' };
    let fetches = 0;
    const fetchBooks = vi.spyOn(api, 'fetchBooks').mockImplementation(async () => {
      fetches += 1;
      return fetches >= 3 ? [...mockBooks, late] : mockBooks;
    });
    vi.spyOn(api, 'uploadBook').mockResolvedValue({ kind: 'ocr', task: ocrTask({ status: 'pending' }) });
    // 卡死判定发生在轮询之前，所以这个 mock 根本不会被调用——正好用来证明「放弃前没再白问一次」
    const fetchOcrTask = vi.spyOn(api, 'fetchOcrTask').mockResolvedValue(ocrTask({ donePages: 12 }));

    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    await openAndUpload(user);
    await screen.findByRole('progressbar', { name: '扫描件识别进度' });

    expect(await screen.findByText(/识别卡住了/, {}, POLL_TIMEOUT)).toBeInTheDocument();
    expect(fetchOcrTask).not.toHaveBeenCalled();
    // 关键：放弃之前必须先去问一次服务端。上次就是漏了这一步，书入库了却看不见。
    expect(fetches).toBe(3);
    expect(fetchBooks).toHaveBeenCalledTimes(3);
    expect(await screen.findByTestId('book-choice-late-book')).toBeInTheDocument();
    // 放弃 ≠ 失败，提示不能把话说死
    expect(screen.getByRole('status')).not.toHaveTextContent('失败');
    expect(screen.queryByRole('progressbar')).toBeNull();
  });

  it('总时长超出预算时同样先刷列表，且提示识别可能仍在后台继续', async () => {
    OCR_POLL_LIMITS.minBudgetMs = 1;
    OCR_POLL_LIMITS.stallMs = 60 * 60 * 1000; // 让「卡死」分支让开路，专门测超预算
    OCR_POLL_LIMITS.intervalMs = 20;
    const fetchBooks = vi.spyOn(api, 'fetchBooks').mockResolvedValue(mockBooks);
    vi.spyOn(api, 'uploadBook').mockResolvedValue({ kind: 'ocr', task: ocrTask({ status: 'pending' }) });
    vi.spyOn(api, 'fetchOcrTask').mockResolvedValue(ocrTask({ donePages: 3 }));

    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    await openAndUpload(user);
    await screen.findByRole('progressbar', { name: '扫描件识别进度' });
    const callsBefore = fetchBooks.mock.calls.length;

    expect(await screen.findByText(/耗时超出预期/, {}, POLL_TIMEOUT)).toBeInTheDocument();
    expect(fetchBooks.mock.calls.length).toBe(callsBefore + 1);
    expect(screen.getByRole('status')).toHaveTextContent('仍在后台继续');
  });

  it('放弃之后不再继续轮询（不能一边放弃一边空转）', async () => {
    OCR_POLL_LIMITS.stallMs = 1;
    OCR_POLL_LIMITS.intervalMs = 20;
    vi.spyOn(api, 'fetchBooks').mockResolvedValue(mockBooks);
    vi.spyOn(api, 'uploadBook').mockResolvedValue({ kind: 'ocr', task: ocrTask({ status: 'pending' }) });
    const fetchOcrTask = vi.spyOn(api, 'fetchOcrTask').mockResolvedValue(ocrTask({ donePages: 1 }));

    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    await openAndUpload(user);
    await screen.findByText(/识别卡住了/, {}, POLL_TIMEOUT);

    const calls = fetchOcrTask.mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 200));
    expect(fetchOcrTask.mock.calls.length).toBe(calls);
    // 按钮要重新可用，不能把用户永久锁在「识别中」
    expect(screen.getByRole('button', { name: /上传新教材/ })).toBeEnabled();
  });
});

describe('刷新页面后接上识别进度', () => {
  it('挂载时读 localStorage 里的任务 id 继续轮询', async () => {
    localStorage.setItem('ai_reader.ocrTaskId', 't1');
    OCR_POLL_LIMITS.intervalMs = 20;
    vi.spyOn(api, 'fetchBooks').mockResolvedValue(mockBooks);
    const fetchOcrTask = vi
      .spyOn(api, 'fetchOcrTask')
      .mockResolvedValue(ocrTask({ status: 'running', donePages: 88, percent: 29 }));

    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    // 没有上传动作，纯粹靠 localStorage 里的 id 接上
    await user.click(screen.getByRole('button', { name: /更换教材/ }));

    expect(await screen.findByText(/88 \/ 300 页/, {}, POLL_TIMEOUT)).toBeInTheDocument();
    expect(fetchOcrTask).toHaveBeenCalledWith('t1');
  });

  it('任务进入终态后清掉存储，别让下次打开又去问一个已经结束的任务', async () => {
    localStorage.setItem('ai_reader.ocrTaskId', 't1');
    OCR_POLL_LIMITS.intervalMs = 20;
    vi.spyOn(api, 'fetchBooks').mockResolvedValue(mockBooks);
    vi.spyOn(api, 'fetchOcrTask').mockResolvedValue(
      ocrTask({ status: 'done', donePages: 300, bookId: mockBooks[0].id }),
    );

    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    await user.click(screen.getByRole('button', { name: /更换教材/ }));

    await screen.findByText(/识别完成，已导入知识库/, {}, POLL_TIMEOUT);
    expect(localStorage.getItem('ai_reader.ocrTaskId')).toBeNull();
  });

  it('任务已被服务重启清掉（404）时如实说中断，并清掉存储', async () => {
    localStorage.setItem('ai_reader.ocrTaskId', 't1');
    OCR_POLL_LIMITS.intervalMs = 20;
    vi.spyOn(api, 'fetchBooks').mockResolvedValue(mockBooks);
    vi.spyOn(api, 'fetchOcrTask').mockResolvedValue(null);

    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    await user.click(screen.getByRole('button', { name: /更换教材/ }));

    expect(await screen.findByText(/扫描件识别被服务重启打断/, {}, POLL_TIMEOUT)).toBeInTheDocument();
    expect(localStorage.getItem('ai_reader.ocrTaskId')).toBeNull();
  });
});

describe('上传时记住任务 id', () => {
  it('提交成功后写进 localStorage，刷新页面才有东西可接', async () => {
    OCR_POLL_LIMITS.intervalMs = 20;
    vi.spyOn(api, 'fetchBooks').mockResolvedValue(mockBooks);
    vi.spyOn(api, 'uploadBook').mockResolvedValue({ kind: 'ocr', task: ocrTask({ status: 'pending' }) });
    vi.spyOn(api, 'fetchOcrTask').mockResolvedValue(ocrTask({ status: 'running', donePages: 5 }));

    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    await openAndUpload(user);

    await waitFor(() => expect(localStorage.getItem('ai_reader.ocrTaskId')).toBe('t1'));
  });
});
