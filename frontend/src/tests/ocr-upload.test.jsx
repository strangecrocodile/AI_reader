import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import App from '../App.jsx';
import { api, MAX_UPLOAD_BYTES } from '../services/api.js';
import { books as mockBooks } from '../data/books.js';
import { BookProvider } from '../state/BookContext.jsx';
import { ToastProvider } from '../state/ToastContext.jsx';

/**
 * 扫描件上传（后端 202 + 轮询）的交互测试。
 *
 * 轮询间隔是 1500ms，所以凡是「等下一轮之后才有结果」的断言都得放宽 waitFor
 * 的超时，默认的 1000ms 根本等不到第一次轮询。
 */
const POLL_TIMEOUT = { timeout: 5000 };

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

/** 造一个后端的 OCR 任务结构（字段与 serializers 一致，camelCase）。 */
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

/** 打开弹窗并选一个文件上传。 */
async function openAndUpload(user, { name = 'scan.pdf', size = null } = {}) {
  await user.click(screen.getByRole('button', { name: /更换教材/ }));
  const file = new File(['%PDF-scan'], name, { type: 'application/pdf' });
  // jsdom 里造不出 200MB 的真文件，直接把 size 盖掉
  if (size !== null) Object.defineProperty(file, 'size', { value: size });
  fireEvent.change(screen.getByLabelText('选择教材文件'), { target: { files: [file] } });
  return file;
}

describe('扫描件上传（OCR 异步任务）', () => {
  it('上传后先显示任务快照，再随轮询推进进度，并禁止再传第二本', async () => {
    vi.spyOn(api, 'fetchBooks').mockResolvedValue(mockBooks);
    vi.spyOn(api, 'uploadBook').mockResolvedValue({
      kind: 'ocr',
      task: ocrTask({ status: 'pending' }),
    });
    const fetchOcrTask = vi
      .spyOn(api, 'fetchOcrTask')
      .mockResolvedValue(ocrTask({ donePages: 42, percent: 14 }));

    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');

    await openAndUpload(user);

    // 上传响应里就带着任务快照，不用等第一轮轮询才画进度条
    const bar = await screen.findByRole('progressbar', { name: '扫描件识别进度' });
    expect(bar).toHaveAttribute('max', '300');
    expect(screen.getByText(/《模式识别及MATLAB实现》是扫描件/)).toBeInTheDocument();

    // 第一次轮询走完之后进度跟上来
    await waitFor(() => expect(screen.getByText(/42 \/ 300 页/)).toBeInTheDocument(), POLL_TIMEOUT);
    expect(fetchOcrTask).toHaveBeenCalledWith('t1');

    // 同一时刻只跟得住一个任务，按钮要说清为什么点不动
    expect(screen.getByRole('button', { name: '识别中，暂不能再上传' })).toBeDisabled();
  });

  it('识别完成后刷新列表、切到新教材并提示', async () => {
    const scanned = {
      ...mockBooks[0],
      id: 'scanned-book',
      title: '扫描教材',
      cover: { ...mockBooks[0].cover, lines: ['扫描教材'] },
    };
    const fetchBooks = vi
      .spyOn(api, 'fetchBooks')
      .mockResolvedValueOnce(mockBooks)
      .mockResolvedValue([...mockBooks, scanned]);
    vi.spyOn(api, 'uploadBook').mockResolvedValue({
      kind: 'ocr',
      task: ocrTask({ status: 'pending', title: '扫描教材' }),
    });
    vi.spyOn(api, 'fetchOcrTask').mockResolvedValue(
      ocrTask({ status: 'done', title: '扫描教材', donePages: 300, bookId: 'scanned-book' }),
    );

    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    await openAndUpload(user);
    await screen.findByRole('progressbar', { name: '扫描件识别进度' });

    expect(
      await screen.findByText('《扫描教材》扫描件识别完成，已导入知识库', {}, POLL_TIMEOUT),
    ).toBeInTheDocument();
    // 进度块收掉，教材切过去（先 refreshBooks 再切，避免切到列表里还没有的书）
    expect(screen.queryByRole('progressbar')).toBeNull();
    expect(fetchBooks).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(screen.getByTestId('book-cover')).toHaveTextContent('扫描教材'));
  });

  it('识别期间允许关掉弹窗，完成后仍然会通知——识别跑在后端，不该扣住用户十分钟', async () => {
    vi.spyOn(api, 'fetchBooks').mockResolvedValue(mockBooks);
    vi.spyOn(api, 'uploadBook').mockResolvedValue({
      kind: 'ocr',
      task: ocrTask({ status: 'pending', title: '扫描教材' }),
    });
    const fetchOcrTask = vi
      .spyOn(api, 'fetchOcrTask')
      .mockResolvedValue(ocrTask({ status: 'done', title: '扫描教材', bookId: mockBooks[0].id }));

    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    await openAndUpload(user);
    await screen.findByRole('progressbar', { name: '扫描件识别进度' });

    await user.click(screen.getByRole('button', { name: '关闭' }));
    expect(screen.queryByRole('dialog')).toBeNull();

    // 关掉窗口不等于放弃任务：轮询继续，结果照报
    expect(
      await screen.findByText('《扫描教材》扫描件识别完成，已导入知识库', {}, POLL_TIMEOUT),
    ).toBeInTheDocument();
    expect(fetchOcrTask).toHaveBeenCalled();
  });

  it('识别失败时说清「一个字都没入库」，并给出重传建议', async () => {
    vi.spyOn(api, 'fetchBooks').mockResolvedValue(mockBooks);
    vi.spyOn(api, 'uploadBook').mockResolvedValue({
      kind: 'ocr',
      task: ocrTask({ status: 'pending', title: '扫描教材' }),
    });
    vi.spyOn(api, 'fetchOcrTask').mockResolvedValue(
      ocrTask({
        status: 'failed',
        title: '扫描教材',
        donePages: 120,
        message: '已识别 120/300 页后失败：page 121 is not a valid page',
      }),
    );

    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    await openAndUpload(user);
    await screen.findByRole('progressbar', { name: '扫描件识别进度' });

    const alert = await screen.findByRole('alert', {}, POLL_TIMEOUT);
    expect(alert).toHaveTextContent('《扫描教材》没能识别成功');
    expect(alert).toHaveTextContent('已识别 120/300 页后失败');
    // 全有或全无：得说清半本书不会被留下凑合看
    expect(alert).toHaveTextContent('不会入库');

    // 弹窗可能已经被关掉，所以 toast 还得再报一次
    expect(screen.getByText(/识别失败：已识别 120\/300 页后失败/)).toBeInTheDocument();
    expect(screen.queryByRole('progressbar')).toBeNull();
  });

  it('后端重启导致任务消失时报告中断，而不是一直转圈', async () => {
    vi.spyOn(api, 'fetchBooks').mockResolvedValue(mockBooks);
    vi.spyOn(api, 'uploadBook').mockResolvedValue({
      kind: 'ocr',
      task: ocrTask({ status: 'pending' }),
    });
    vi.spyOn(api, 'fetchOcrTask').mockResolvedValue(null);

    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    await openAndUpload(user);
    await screen.findByRole('progressbar', { name: '扫描件识别进度' });

    expect(
      await screen.findByText(/扫描件识别被服务重启打断/, {}, POLL_TIMEOUT),
    ).toBeInTheDocument();
    expect(screen.queryByRole('progressbar')).toBeNull();

    // 中断之后不能把用户卡在「识别中」——按钮要重新可用
    expect(screen.getByRole('button', { name: /上传新教材/ })).toBeEnabled();
  });

  it('超过体积上限的文件根本不发起上传', async () => {
    const uploadBook = vi.spyOn(api, 'uploadBook');
    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');

    await openAndUpload(user, { name: 'huge.pdf', size: MAX_UPLOAD_BYTES + 1 });

    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('文件超过 200 MB'),
    );
    expect(uploadBook).not.toHaveBeenCalled();
  });

  it('解析受限的提示不再教用户自己转换扫描件（扫描件已经自动走 OCR）', async () => {
    const thin = {
      ...mockBooks[0],
      id: 'thin',
      title: '窄教材',
      contentWarning: '整本教材只解析出 6 个字的正文，内容可能大部分没被读出来',
    };
    vi.spyOn(api, 'fetchBooks').mockResolvedValue(mockBooks);
    vi.spyOn(api, 'uploadBook').mockResolvedValue({ kind: 'book', book: thin });

    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    await openAndUpload(user, { name: 'course.docx' });

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('表格里');
    expect(alert).not.toHaveTextContent('扫描图片');
  });
});
