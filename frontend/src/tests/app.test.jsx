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
    await user.click(screen.getByRole('button', { name: /线性代数/ }));

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
    const fetchBooks = vi
      .spyOn(api, 'fetchBooks')
      .mockResolvedValueOnce(mockBooks)
      .mockResolvedValueOnce([...mockBooks, uploaded]);
    const uploadBook = vi.spyOn(api, 'uploadBook').mockResolvedValue(uploaded);
    const user = userEvent.setup();

    renderApp();
    await screen.findByText('正在学习的教材');
    await user.click(screen.getByRole('button', { name: /更换教材/ }));

    const file = new File(['%PDF-demo'], 'new-book.pdf', { type: 'application/pdf' });
    fireEvent.change(screen.getByLabelText('选择教材文件'), { target: { files: [file] } });

    await waitFor(() => expect(uploadBook).toHaveBeenCalledWith(file));
    expect(fetchBooks).toHaveBeenCalledTimes(2);
    expect(await screen.findByTestId('book-cover')).toHaveTextContent('新上传教材');
    expect(screen.getByText('《新上传教材》已上传并识别 3 个章节')).toBeInTheDocument();

    uploadBook.mockRestore();
    fetchBooks.mockRestore();
  });

  it('选择 Word 教材时同样可以上传并切换', async () => {
    const uploaded = {
      ...mockBooks[0],
      id: 'uploaded-docx',
      title: '微积分入门（Word 版）',
      cover: { ...mockBooks[0].cover, lines: ['微积分入门（Word 版）'] },
    };
    const fetchBooks = vi
      .spyOn(api, 'fetchBooks')
      .mockResolvedValueOnce(mockBooks)
      .mockResolvedValueOnce([...mockBooks, uploaded]);
    const uploadBook = vi.spyOn(api, 'uploadBook').mockResolvedValue(uploaded);
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
  it('拖选原文后提问，展示回答与教材依据', async () => {
    const user = userEvent.setup();
    renderApp(['/study/calc7/ch2']);
    const paper = await screen.findByTestId('paper');

    // 模拟拖选原文：对第一段创建选区并触发 mouseup
    const firstSpan = paper.querySelector('p .source');
    const range = document.createRange();
    range.selectNodeContents(firstSpan);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    fireEvent.mouseUp(paper);

    const label = screen.getByTestId('selection-label');
    expect(label).toHaveClass('show');
    expect(label).toHaveTextContent('已选原文');

    await user.type(screen.getByLabelText('提问输入框'), '这段想表达什么？');
    await user.click(screen.getByRole('button', { name: '提问' }));

    const answer = await screen.findByTestId('answer', undefined, { timeout: 3000 });
    expect(answer).toHaveTextContent('AI讲师');
    expect(answer).toHaveTextContent('Δy / Δx');
    const chips = screen.getAllByRole('button', { name: /教材依据/ });
    expect(chips.length).toBeGreaterThan(0);
  });

  it('提问回答后清除选中状态', async () => {
    const user = userEvent.setup();
    renderApp(['/study/calc7/ch2']);
    const paper = await screen.findByTestId('paper');

    const range = document.createRange();
    const firstSpan = paper.querySelector('p .source');
    range.selectNodeContents(firstSpan);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    fireEvent.mouseUp(paper);

    await user.type(screen.getByLabelText('提问输入框'), '为什么？');
    await user.click(screen.getByRole('button', { name: '提问' }));

    await screen.findByTestId('answer', undefined, { timeout: 3000 });
    expect(screen.getByTestId('selection-label')).not.toHaveClass('show');
  });
});
