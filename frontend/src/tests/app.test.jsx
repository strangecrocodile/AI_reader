import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import App from '../App.jsx';
import { api } from '../services/api.js';
import { books as mockBooks } from '../data/books.js';
import { BookProvider } from '../state/BookContext.jsx';
import { ToastProvider } from '../state/ToastContext.jsx';

beforeEach(() => {
  // 隔离测试间共享的 localStorage（当前教材选择 + 学习事件）
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderApp(initialEntries = ['/']) {
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

/**
 * 让 `fetchBooks` 表现得像真后端：**只有上传成功之后，列表里才会多出新教材**。
 *
 * 换教材弹窗现在每次打开都会重读一次列表（自愈用），所以「第一次返回 A、第二次返回
 * B」这种写死的调用序列对不上号了——必须让返回值取决于上传有没有发生过。
 *
 * @returns {{ fetchBooks: import('vitest').Mock, uploadBook: import('vitest').Mock }}
 */
function serveUploadedBook(uploaded) {
  let uploadedYet = false;
  const fetchBooks = vi
    .spyOn(api, 'fetchBooks')
    .mockImplementation(async () => (uploadedYet ? [...mockBooks, uploaded] : mockBooks));
  const uploadBook = vi.spyOn(api, 'uploadBook').mockImplementation(async () => {
    uploadedYet = true;
    return { kind: 'book', book: uploaded };
  });
  return { fetchBooks, uploadBook };
}

/** 模拟在原文里拖选第一段（带锚点的段落）。 */
function selectFirstParagraph(paper) {
  const firstSpan = paper.querySelector('p .source');
  const range = document.createRange();
  range.selectNodeContents(firstSpan);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
  fireEvent.mouseUp(paper);
}

describe('主页', () => {
  it('加载后展示默认教材、学习计划与章节目录', async () => {
    renderApp();
    expect(screen.getByText('正在加载教材…')).toBeInTheDocument();

    await screen.findByText('正在学习的教材');
    expect(screen.getByTestId('book-progress')).toHaveTextContent('18% 已完成');
    expect(screen.getByTestId('book-cover')).toHaveTextContent('高等数学');
    expect(screen.getByText('从变化率，')).toBeInTheDocument();
    expect(
      screen.getByText('理解导数的定义，并能解释它与「瞬时变化率」的关系'),
    ).toBeInTheDocument();
    expect(screen.getByText('函数与极限')).toBeInTheDocument();
    expect(screen.getByText('导数与微分')).toBeInTheDocument();
    expect(screen.getByText('微分中值定理')).toBeInTheDocument();
  });

  it('更换教材后主页同步更新', async () => {
    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');

    await user.click(screen.getByRole('button', { name: /更换教材/ }));
    // 按 testid 取而不是按书名：行里现在还有一个「删除《线性代数》」按钮，按书名会命中两个
    await user.click(screen.getByTestId('book-choice-linalg6'));

    expect(screen.getByTestId('book-progress')).toHaveTextContent('6% 已完成');
    expect(screen.getByTestId('book-cover')).toHaveTextContent('线性代数');
  });

  it('选择 PDF 后上传、刷新教材列表并切换到新教材', async () => {
    const uploaded = {
      ...mockBooks[0],
      id: 'uploaded-book',
      title: '新上传教材',
      cover: { ...mockBooks[0].cover, lines: ['新上传教材'] },
    };
    const { fetchBooks, uploadBook } = serveUploadedBook(uploaded);
    const user = userEvent.setup();

    renderApp();
    await screen.findByText('正在学习的教材');
    await user.click(screen.getByRole('button', { name: /更换教材/ }));

    const file = new File(['%PDF-demo'], 'new-book.pdf', { type: 'application/pdf' });
    fireEvent.change(screen.getByLabelText('选择教材文件'), { target: { files: [file] } });

    await waitFor(() => expect(uploadBook).toHaveBeenCalledWith(file));
    // 3 次 = 挂载 + 开弹窗时自愈重读 + 上传成功后刷新。删掉上传后那次刷新就只剩 2 次，
    // 所以这个数字确实在守着「上传完必须重读列表」。
    expect(fetchBooks).toHaveBeenCalledTimes(3);
    expect(await screen.findByTestId('book-cover')).toHaveTextContent('新上传教材');
    expect(screen.getByText('《新上传教材》已上传并识别 3 个章节')).toBeInTheDocument();

    uploadBook.mockRestore();
    fetchBooks.mockRestore();
  });

  it('解析受限时上传后给出提示，且不自动关闭弹窗', async () => {
    const uploaded = {
      ...mockBooks[0],
      id: 'thin',
      title: '窄教材',
      contentWarning: '整本教材只解析出 6 个字的正文，内容可能大部分没被读出来；1 个表格',
      cover: { ...mockBooks[0].cover, lines: ['窄教材'] },
    };
    const { fetchBooks } = serveUploadedBook(uploaded);

    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    await user.click(screen.getByRole('button', { name: /更换教材/ }));

    const file = new File(['docx'], 'course.docx', { type: 'application/docx' });
    fireEvent.change(screen.getByLabelText('选择教材文件'), { target: { files: [file] } });

    // 提示要让用户读完并知道怎么补救，所以弹窗必须留着，不能一闪而过
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('内容可能没被完整读取');
    expect(alert).toHaveTextContent('6 个字');
    expect(alert).toHaveTextContent('1 个表格');
    expect(alert).toHaveTextContent('表格里');
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    // 点「知道了」才关闭；重开时提示不残留
    await user.click(screen.getByRole('button', { name: '知道了，先这样看' }));
    expect(screen.queryByRole('dialog')).toBeNull();

    await user.click(screen.getByRole('button', { name: /更换教材/ }));
    expect(screen.queryByRole('alert')).toBeNull();
    // 提示随教材存库，重开弹窗在教材条目上仍能看到标记
    expect(screen.getByText('⚠ 内容可能没读全')).toBeInTheDocument();

    fetchBooks.mockRestore();
  });

  it('选择 Word 教材时同样可以上传并切换', async () => {
    const uploaded = {
      ...mockBooks[0],
      id: 'uploaded-docx',
      title: '微积分入门（Word 版）',
      cover: { ...mockBooks[0].cover, lines: ['微积分入门（Word 版）'] },
    };
    const { fetchBooks, uploadBook } = serveUploadedBook(uploaded);
    const user = userEvent.setup();

    renderApp();
    await screen.findByText('正在学习的教材');
    await user.click(screen.getByRole('button', { name: /更换教材/ }));

    const file = new File(['PK'], '微积分入门.docx', {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    });
    fireEvent.change(screen.getByLabelText('选择教材文件'), { target: { files: [file] } });

    await waitFor(() => expect(uploadBook).toHaveBeenCalledWith(file));
    expect(await screen.findByTestId('book-cover')).toHaveTextContent('微积分入门（Word 版）');

    uploadBook.mockRestore();
    fetchBooks.mockRestore();
  });

  it('选择不支持的格式时不会发起上传并提示可用格式', async () => {
    const uploadBook = vi.spyOn(api, 'uploadBook');
    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');
    await user.click(screen.getByRole('button', { name: /更换教材/ }));

    const file = new File(['doc'], 'old.doc', { type: 'application/msword' });
    fireEvent.change(screen.getByLabelText('选择教材文件'), { target: { files: [file] } });

    expect(await screen.findByText(/目前支持 PDF \/ Word\(\.docx\)/, { selector: '.upload-hint' })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('目前支持 PDF / Word(.docx)'),
    );
    expect(uploadBook).not.toHaveBeenCalled();
    uploadBook.mockRestore();
  });
});

describe('学习页', () => {
  it('点击「开启今日学习」进入章节学习页并展示原文与讲解', async () => {
    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');

    await user.click(screen.getByRole('button', { name: /开启今日学习/ }));

    const headings = await screen.findAllByText('2.1 导数的概念');
    expect(headings.length).toBeGreaterThan(0);
    expect(screen.getByText(/一个量相对于另一个量的变化率/)).toBeInTheDocument();
    expect(screen.getByText('先抓住「变化率」')).toBeInTheDocument();
    expect(screen.getByTestId('paper')).toHaveTextContent('f′(x₀) = lim');
  });

  it('直接访问章节路由可正常渲染', async () => {
    renderApp(['/study/calc7/ch2']);
    const paper = await screen.findByTestId('paper');
    expect(paper).toHaveTextContent('比值 Δy / Δx 的极限存在');
    expect(screen.getByText('先抓住「变化率」')).toBeInTheDocument();
  });

  it('未准备内容的章节显示占位提示', async () => {
    renderApp(['/study/calc7/ch1']);
    await screen.findByText('本章内容尚未准备');
    expect(screen.getByRole('button', { name: /返回学习计划/ })).toBeInTheDocument();
  });

  it('点击「AI 讲解」中的定位按钮会高亮对应原文锚点', async () => {
    const user = userEvent.setup();
    renderApp(['/study/calc7/ch2']);
    await screen.findByTestId('paper');

    await user.click(screen.getByRole('button', { name: /定位教材：导数定义/ }));

    expect(document.getElementById('source-limit')).toHaveClass('focus');
    expect(screen.getByText('定位教材：导数定义')).toBeInTheDocument();
  });

  it('切换到「知识点大纲」并点击条目可定位原文', async () => {
    const user = userEvent.setup();
    renderApp(['/study/calc7/ch2']);
    await screen.findByTestId('paper');

    await user.click(screen.getByRole('tab', { name: '知识点大纲' }));
    expect(screen.getByText('先用两个点描述一段变化。')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /平均变化率/ }));
    expect(document.getElementById('source-rate')).toHaveClass('focus');
  });
});

describe('真实掌握度', () => {
  /** 用可控的 IntersectionObserver 替身模拟「段落进入视口」。 */
  function stubIntersectionObserver() {
    const observers = [];
    class FakeObserver {
      constructor(callback) {
        this.callback = callback;
        this.nodes = [];
        observers.push(this);
      }

      observe(node) {
        this.nodes.push(node);
      }

      disconnect() {}
    }
    vi.stubGlobal('IntersectionObserver', FakeObserver);
    return observers;
  }

  it('进入章节上报学习事件，掌握度从真实的 0 开始（不再是写死的数字）', async () => {
    renderApp(['/study/calc7/ch2']);

    expect(await screen.findByTestId('mastery-panel')).toBeInTheDocument();
    expect(screen.getByText('掌握度 0%')).toBeInTheDocument();
    expect(screen.getByText('学习中')).toBeInTheDocument();
    expect(screen.getByText(/已读 0\/3 段 · 提问 0 次/)).toBeInTheDocument();
  });

  it('读到段落会累计覆盖度，掌握度随之上升', async () => {
    const observers = stubIntersectionObserver();
    renderApp(['/study/calc7/ch2']);
    await screen.findByTestId('mastery-panel');

    const observer = observers.find((item) => item.nodes.length > 0);
    expect(observer).toBeTruthy();
    observer.callback(
      ['source-rate', 'source-limit', 'source-tangent'].map((sourceId) => ({
        isIntersecting: true,
        target: { dataset: { sourceId } },
      })),
    );

    await waitFor(() => expect(screen.getByText(/已读 3\/3 段/)).toBeInTheDocument());
    expect(screen.getByText('掌握度 67%')).toBeInTheDocument();
  });

  it('提问计入互动度，掌握度按公式变化', async () => {
    const user = userEvent.setup();
    renderApp(['/study/calc7/ch2']);
    await screen.findByTestId('mastery-panel');

    await user.type(screen.getByLabelText('提问输入框'), '这段想表达什么？');
    await user.click(screen.getByRole('button', { name: '提问' }));
    await screen.findByTestId('answer', undefined, { timeout: 3000 });

    await waitFor(() => expect(screen.getByText(/提问 1 次/)).toBeInTheDocument());
    expect(screen.getByText('掌握度 7%')).toBeInTheDocument();
  });

  it('可以手动标记本章学完，状态变为已掌握', async () => {
    const user = userEvent.setup();
    renderApp(['/study/calc7/ch2']);
    await screen.findByTestId('mastery-panel');

    await user.click(screen.getByRole('button', { name: '标记本章学完' }));

    await waitFor(() => expect(screen.getByText('已掌握')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: '标记本章学完' })).not.toBeInTheDocument();
  });
});

describe('知识地图', () => {
  it('导航进入知识地图并展示知识点卡片与关系图谱', async () => {
    const user = userEvent.setup();
    renderApp();
    await screen.findByText('正在学习的教材');

    await user.click(screen.getByRole('link', { name: '知识地图' }));

    expect(await screen.findByText('把读过的内容，连成一张地图。')).toBeInTheDocument();
    expect(screen.getByText('知识点卡片')).toBeInTheDocument();
    expect(screen.getByTestId('knowledge-graph')).toBeInTheDocument();
    expect(screen.getAllByText('先抓住「变化率」').length).toBeGreaterThan(0);
  });

  it('点击知识点后可以回到对应章节学习页', async () => {
    const user = userEvent.setup();
    renderApp(['/knowledge']);
    await screen.findByText('知识点卡片');

    await user.click(screen.getByRole('button', { name: /回到教材原文/ }));

    expect(await screen.findByTestId('paper')).toBeInTheDocument();
    await waitFor(() => expect(document.getElementById('source-rate')).toHaveClass('focus'));
  });

  it('图谱区分前置依赖与学习顺序，并单独列出教材外前置', async () => {
    renderApp(['/knowledge']);
    const graph = await screen.findByTestId('knowledge-graph');

    expect(graph.querySelectorAll('line.graph-line.prerequisite').length).toBeGreaterThan(0);
    expect(graph.querySelectorAll('line.graph-line.sequence').length).toBeGreaterThan(0);
    expect(screen.getByText('前置依赖')).toBeInTheDocument();
    expect(screen.getByText('学习顺序')).toBeInTheDocument();

    const external = screen.getByTestId('knowledge-external');
    expect(external).toHaveTextContent('教材中未出现的前置概念');
    expect(external).toHaveTextContent('极限');
  });

  it('知识点详情展示前置概念，教材外的前置会被标注', async () => {
    renderApp(['/knowledge']);
    await screen.findByText('知识点卡片');

    // 默认选中第一个知识点，它依赖的「极限」在演示数据里没有卡片
    expect(await screen.findByText('前置概念')).toBeInTheDocument();
    expect(screen.getByText('极限（教材外）')).toBeInTheDocument();
  });
});

describe('划词问答', () => {
  it('拖选原文后提问，回答逐块补齐并附带教材依据', async () => {
    const user = userEvent.setup();
    renderApp(['/study/calc7/ch2']);
    const paper = await screen.findByTestId('paper');

    // 模拟拖选原文：对第一段创建选区并触发 mouseup
    selectFirstParagraph(paper);

    const label = screen.getByTestId('selection-label');
    expect(label).toHaveClass('show');
    expect(label).toHaveTextContent('已选原文');

    await user.type(screen.getByLabelText('提问输入框'), '这段想表达什么？');
    await user.click(screen.getByRole('button', { name: '提问' }));

    const answer = await screen.findByTestId('answer', undefined, { timeout: 3000 });
    expect(answer).toHaveTextContent('AI讲师');
    await waitFor(() => expect(answer).toHaveTextContent('Δy / Δx'), { timeout: 3000 });
    await waitFor(() =>
      expect(screen.getAllByRole('button', { name: /教材依据/ }).length).toBeGreaterThan(0),
    );
  });

  it('回答以流式方式显示：先出现流式气泡，再逐块补齐', async () => {
    const user = userEvent.setup();
    renderApp(['/study/calc7/ch2']);
    await screen.findByTestId('paper');

    await user.type(screen.getByLabelText('提问输入框'), '这段想表达什么？');
    await user.click(screen.getByRole('button', { name: '提问' }));

    const answer = await screen.findByTestId('answer');
    expect(answer).toHaveAttribute('data-streaming');

    await waitFor(() => expect(answer).not.toHaveAttribute('data-streaming'), { timeout: 3000 });
    await waitFor(() => expect(answer).toHaveTextContent('Δy / Δx'));
  });

  it('提问回答后清除选中状态', async () => {
    const user = userEvent.setup();
    renderApp(['/study/calc7/ch2']);
    const paper = await screen.findByTestId('paper');

    selectFirstParagraph(paper);

    await user.type(screen.getByLabelText('提问输入框'), '为什么？');
    await user.click(screen.getByRole('button', { name: '提问' }));

    await waitFor(
      () => expect(screen.getByTestId('selection-label')).not.toHaveClass('show'),
      { timeout: 3000 },
    );
  });

  it('依据来自其他章节时标出章节名并可跳过去核对', async () => {
    const user = userEvent.setup();
    const streamSpy = vi.spyOn(api, 'askStream').mockImplementation(async (_params, handlers) => {
      handlers.onDelta?.('导数定义见第 3 章 ');
      handlers.onDone?.({
        answer: '导数定义见第 3 章 [1]',
        sources: ['source-limit'],
        sourceDetails: [
          {
            id: 'source-limit',
            page: 47,
            text: '比值 Δy / Δx 的极限存在',
            chapterId: 'ch3',
            chapterTitle: '微分中值定理',
          },
        ],
        scope: 'book',
      });
    });

    renderApp(['/study/calc7/ch2']);
    await screen.findByTestId('paper');
    await user.type(screen.getByLabelText('提问输入框'), '导数的定义是什么？');
    await user.click(screen.getByRole('button', { name: '提问' }));

    await waitFor(() => expect(screen.getByText(/本章依据不足，已扩展到全书检索/)).toBeInTheDocument());
    const chip = await screen.findByRole('button', { name: /微分中值定理 · 第 47 页/ });
    await user.click(chip);

    // 跳到对应章节（演示数据里 ch3 没有正文，显示占位页即可证明路由生效）
    expect(await screen.findByText('本章内容尚未准备')).toBeInTheDocument();
    streamSpy.mockRestore();
  });
});

describe('划词气泡与追问线程', () => {
  it('选中原文后在选区旁出现气泡按钮', async () => {
    renderApp(['/study/calc7/ch2']);
    const paper = await screen.findByTestId('paper');
    expect(screen.queryByTestId('selection-bubble')).not.toBeInTheDocument();

    selectFirstParagraph(paper);

    const bubble = await screen.findByTestId('selection-bubble');
    expect(bubble).toHaveTextContent('问 AI');
  });

  it('点击气泡会为该段原文开一条追问线程并打开浮层', async () => {
    const user = userEvent.setup();
    const createSpy = vi.spyOn(api, 'createThread');
    renderApp(['/study/calc7/ch2']);
    const paper = await screen.findByTestId('paper');
    selectFirstParagraph(paper);

    await user.click(await screen.findByTestId('selection-bubble'));

    expect(await screen.findByTestId('selection-panel')).toBeInTheDocument();
    expect(createSpy).toHaveBeenCalledWith(
      expect.objectContaining({ bookId: 'calc7', chapterId: 'ch2', anchorId: 'source-rate' }),
    );
    expect(
      screen.getByText('就这段原文提问，回答会带上教材依据，可以连续追问。'),
    ).toBeInTheDocument();
    createSpy.mockRestore();
  });

  it('气泡内追问会流式回答，并出现在本章的追问线程列表里', async () => {
    const user = userEvent.setup();
    renderApp(['/study/calc7/ch2']);
    const paper = await screen.findByTestId('paper');
    selectFirstParagraph(paper);
    await user.click(await screen.findByTestId('selection-bubble'));

    await user.type(screen.getByLabelText('追问输入框'), '这段想表达什么？');
    await user.click(screen.getByRole('button', { name: '追问' }));

    const panel = await screen.findByTestId('selection-panel');
    await waitFor(() => expect(panel).toHaveTextContent('AI讲师'), { timeout: 3000 });
    await waitFor(() => expect(panel).toHaveTextContent('Δy / Δx'), { timeout: 3000 });

    const list = await screen.findByTestId('thread-list');
    expect(list).toHaveTextContent('一个量相对于另一个量的变化率');
  });

  it('气泡浮层可以拖动、可以关闭', async () => {
    const user = userEvent.setup();
    renderApp(['/study/calc7/ch2']);
    const paper = await screen.findByTestId('paper');
    selectFirstParagraph(paper);
    await user.click(await screen.findByTestId('selection-bubble'));

    const panel = screen.getByTestId('selection-panel');
    const before = panel.style.left;
    fireEvent.mouseDown(screen.getByTestId('selection-panel-handle'), {
      clientX: 100,
      clientY: 100,
      button: 0,
    });
    fireEvent.mouseMove(window, { clientX: 180, clientY: 150 });
    fireEvent.mouseUp(window);
    expect(panel.style.left).not.toBe(before);

    await user.click(screen.getByRole('button', { name: '关闭追问气泡' }));
    expect(screen.queryByTestId('selection-panel')).not.toBeInTheDocument();
  });

  it('右栏直接提问同样落在追问线程里，标题取首个问题', async () => {
    const user = userEvent.setup();
    renderApp(['/study/calc7/ch2']);
    await screen.findByTestId('mastery-panel');

    await user.type(screen.getByLabelText('提问输入框'), '为什么一定要取极限？');
    await user.click(screen.getByRole('button', { name: '提问' }));

    const answer = await screen.findByTestId('answer', undefined, { timeout: 3000 });
    await waitFor(() => expect(answer).toHaveTextContent('Δx'), { timeout: 3000 });
    expect(await screen.findByTestId('thread-list')).toHaveTextContent('为什么一定要取极限？');
  });

  it('线程可以从列表里删除', async () => {
    const user = userEvent.setup();
    renderApp(['/study/calc7/ch2']);
    const paper = await screen.findByTestId('paper');
    selectFirstParagraph(paper);
    await user.click(await screen.findByTestId('selection-bubble'));
    await user.type(screen.getByLabelText('追问输入框'), '这段想表达什么？');
    await user.click(screen.getByRole('button', { name: '追问' }));
    await screen.findByTestId('thread-list');

    await user.click(screen.getByRole('button', { name: /删除线程/ }));

    await waitFor(() => expect(screen.queryByTestId('thread-list')).not.toBeInTheDocument());
  });
});

describe('空态与异常兜底', () => {
  it('没有任何教材时主页给出上传引导，而不是白屏', async () => {
    const user = userEvent.setup();
    vi.spyOn(api, 'fetchBooks').mockResolvedValue([]);

    renderApp(['/']);

    expect(await screen.findByText('还没有教材')).toBeInTheDocument();
    expect(screen.getByText(/make_demo_pdf\.py/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '上传教材' }));
    expect(screen.getByText('更换教材')).toBeInTheDocument();
  });

  it('教材接口失败时给出错误态，重试成功后恢复', async () => {
    const user = userEvent.setup();
    const spy = vi.spyOn(api, 'fetchBooks').mockRejectedValueOnce(new Error('后端没起来'));

    renderApp(['/']);

    expect(await screen.findByText('连不上教材服务')).toBeInTheDocument();
    expect(screen.getByText(/后端没起来/)).toBeInTheDocument();

    spy.mockResolvedValueOnce(mockBooks);
    await user.click(screen.getByRole('button', { name: '重试' }));

    expect(await screen.findByText('正在学习的教材')).toBeInTheDocument();
  });

  it('没有教材时知识地图给出引导，而不是一直转圈', async () => {
    vi.spyOn(api, 'fetchBooks').mockResolvedValue([]);

    renderApp(['/knowledge']);

    expect(await screen.findByText('还没有教材')).toBeInTheDocument();
    expect(screen.queryByText('正在整理知识地图…')).not.toBeInTheDocument();
  });

  it('未知地址显示 404 页，而不是空白', async () => {
    renderApp(['/does-not-exist']);

    expect(await screen.findByText('这个页面不存在')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '返回学习计划' })).toBeInTheDocument();
  });

  it('顶栏「学习报告」标为即将上线，不做成死链接', async () => {
    renderApp(['/']);
    await screen.findByText('正在学习的教材');

    const item = screen.getByText('学习报告');
    expect(item).toHaveAttribute('aria-disabled', 'true');
    expect(item.closest('a')).toBeNull();
    expect(screen.getByText('即将上线')).toBeInTheDocument();
  });

  it('后端返回 learned 的章节也显示已完成标记', async () => {
    const learnedBook = {
      ...mockBooks[0],
      chapters: mockBooks[0].chapters.map((chapter, index) =>
        index === 0 ? { ...chapter, status: 'learned', meta: '已完成' } : chapter,
      ),
    };
    vi.spyOn(api, 'fetchBooks').mockResolvedValue([learnedBook]);

    renderApp(['/']);

    await screen.findByText('正在学习的教材');
    expect(screen.getByText('✓')).toBeInTheDocument();
  });
});

describe('章节导航与分页阅读', () => {
  /**
   * 让段落块「量出」固定高度。
   * jsdom 没有排版引擎，`getBoundingClientRect()` 一律返回 0——不伪造的话
   * 分页永远只有一页，多页逻辑就测不到了。
   */
  function stubBlockLayout(blockHeight = 400) {
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function measure() {
      const index = this.dataset?.blockIndex;
      const top = index === undefined ? 0 : Number(index) * blockHeight;
      const bottom = index === undefined ? 0 : top + blockHeight;
      return {
        top,
        bottom,
        height: bottom - top,
        left: 0,
        right: 0,
        width: 0,
        x: 0,
        y: top,
        toJSON() {},
      };
    });
  }

  it('学习页顶部提供章节导航，列出本章所在教材的全部章节', async () => {
    renderApp(['/study/calc7/ch2']);
    await screen.findByTestId('paper');

    const select = screen.getByLabelText('选择章节');
    expect(select).toHaveValue('ch2');
    expect(Array.from(select.options).map((option) => option.textContent)).toEqual([
      '01 · 函数与极限',
      '02 · 导数与微分',
      '03 · 微分中值定理',
    ]);
  });

  it('点「下一章」跳到下一章（这里落到了未准备内容的占位页）', async () => {
    const user = userEvent.setup();
    renderApp(['/study/calc7/ch2']);
    await screen.findByTestId('paper');

    expect(screen.getByRole('button', { name: /上一章/ })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: /下一章/ }));

    await screen.findByText('本章内容尚未准备');
  });

  it('切到分页模式：按段落高度分页并显示页码，首尾页按钮正确禁用', async () => {
    stubBlockLayout(400);
    renderApp(['/study/calc7/ch2']);
    await screen.findByTestId('paper');

    expect(screen.queryByText(/第 1 \/ \d+ 页/)).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: '分页' }));

    // 本章 5 个段落块、每块 400px，整页 660px → 一块一页，共 5 页
    expect(screen.getByText('第 1 / 5 页')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /上一页/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /下一页/ })).toBeEnabled();
  });

  it('翻页按钮与 ←→ 方向键都能翻页，到末页停住不越界', async () => {
    stubBlockLayout(400);
    renderApp(['/study/calc7/ch2']);
    const paper = await screen.findByTestId('paper');
    fireEvent.click(screen.getByRole('button', { name: '分页' }));

    fireEvent.click(screen.getByRole('button', { name: /下一页/ }));
    expect(screen.getByText('第 2 / 5 页')).toBeInTheDocument();

    fireEvent.keyDown(paper, { key: 'ArrowRight' });
    expect(screen.getByText('第 3 / 5 页')).toBeInTheDocument();

    fireEvent.keyDown(paper, { key: 'ArrowLeft' });
    expect(screen.getByText('第 2 / 5 页')).toBeInTheDocument();

    for (let i = 0; i < 5; i += 1) {
      fireEvent.click(screen.getByRole('button', { name: /下一页/ }));
    }
    expect(screen.getByText('第 5 / 5 页')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /下一页/ })).toBeDisabled();
  });

  it('分页模式下全部段落仍在 DOM 里：划词与锚点定位不受翻页影响', async () => {
    stubBlockLayout(400);
    renderApp(['/study/calc7/ch2']);
    const paper = await screen.findByTestId('paper');

    fireEvent.click(screen.getByRole('button', { name: '分页' }));

    // 只裁切、不卸载——卸载了就没法划选「上一页」的原文，锚点也定位不到
    expect(paper.querySelectorAll('[data-block-index]')).toHaveLength(5);
    expect(document.getElementById('source-rate')).toBeInTheDocument();
  });

  it('锚点定位时先翻到它所在的那一页', async () => {
    const user = userEvent.setup();
    stubBlockLayout(400);
    renderApp(['/study/calc7/ch2']);
    await screen.findByTestId('paper');
    fireEvent.click(screen.getByRole('button', { name: '分页' }));

    // source-limit 在第 3 个段落块上（每块一页）→ 应翻到第 3 页
    await user.click(screen.getByRole('button', { name: /定位教材：导数定义/ }));

    expect(await screen.findByText('第 3 / 5 页')).toBeInTheDocument();
    expect(document.getElementById('source-limit')).toHaveClass('focus');
  });

  it('切到分页会把阅读方式记在本地', async () => {
    stubBlockLayout(400);
    renderApp(['/study/calc7/ch2']);
    await screen.findByTestId('paper');

    fireEvent.click(screen.getByRole('button', { name: '分页' }));

    expect(localStorage.getItem('ai_reader.viewMode')).toBe('page');
  });

  it('本地记着分页时，重新进入学习页直接就是分页', async () => {
    stubBlockLayout(400);
    localStorage.setItem('ai_reader.viewMode', 'page');

    renderApp(['/study/calc7/ch2']);
    await screen.findByTestId('paper');

    expect(screen.getByRole('button', { name: '分页' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('第 1 / 5 页')).toBeInTheDocument();
  });
});
