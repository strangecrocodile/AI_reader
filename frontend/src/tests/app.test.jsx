import { beforeEach, describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import App from '../App.jsx';
import { BookProvider } from '../state/BookContext.jsx';
import { ToastProvider } from '../state/ToastContext.jsx';

beforeEach(() => {
  // 隔离测试间共享的 localStorage（当前教材选择）
  localStorage.clear();
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
    expect(document.getElementById('source-rate')).toHaveClass('focus');
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
