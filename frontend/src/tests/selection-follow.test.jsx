import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import App from '../App.jsx';
import { BookProvider } from '../state/BookContext.jsx';
import { ToastProvider } from '../state/ToastContext.jsx';

/**
 * 划词气泡必须跟着选区走。
 *
 * 崩溃点：选区时量到的是**当时的视口坐标**，而气泡是 `position: fixed`。用户一滚动，
 * 原文移走了、气泡却钉在屏幕上不动——它看着还在指着一段早已不在那里的文字，点开问的
 * 内容也就跟眼前看到的对不上了。
 *
 * jsdom 没有布局，`getBoundingClientRect` 恒返回全零，所以这里**显式 stub** 出矩形，
 * 再用 scroll 事件驱动重算——否则这个 bug 在测试里根本不可见（这也是它当初能溜过去的原因）。
 */

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

function renderApp() {
  return render(
    <MemoryRouter initialEntries={['/study/calc7/ch2']}>
      <BookProvider>
        <ToastProvider>
          <App />
        </ToastProvider>
      </BookProvider>
    </MemoryRouter>,
  );
}

/**
 * jsdom **没有实现** `Range.prototype.getBoundingClientRect`（属性压根不存在，
 * 所以只能定义、不能 spy）。这里装一个读 `currentRect` 的假实现，restore 时删掉。
 */
let currentRect = { top: 0, bottom: 0, left: 100, width: 200 };

beforeAll(() => {
  Range.prototype.getBoundingClientRect = function getBoundingClientRect() {
    return {
      top: currentRect.top,
      bottom: currentRect.bottom,
      left: currentRect.left,
      right: currentRect.left + currentRect.width,
      width: currentRect.width,
      height: currentRect.bottom - currentRect.top,
      x: currentRect.left,
      y: currentRect.top,
    };
  };
});

afterAll(() => {
  delete Range.prototype.getBoundingClientRect;
});

/** 让选区报出一个指定的视口矩形。 */
function setSelectionRect(rect) {
  currentRect = { left: 100, width: 200, ...rect };
}

/** 模拟在原文里拖选第一段（带锚点的段落）。 */
function selectFirstParagraph() {
  const paper = screen.getByTestId('paper');
  const firstSpan = paper.querySelector('p .source');
  const range = document.createRange();
  range.selectNodeContents(firstSpan);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
  fireEvent.mouseUp(paper);
}

const SELECTED = { top: 280, bottom: 300 };
const AFTER_SCROLL = { top: 80, bottom: 100 };
const OFF_SCREEN = { top: -220, bottom: -200 };

/** 渲染并等到阅读页就绪（演示模式取内容有 200ms 延迟）。 */
async function renderStudyPage() {
  renderApp();
  return screen.findByTestId('paper');
}

describe('划词气泡跟随选区', () => {
  it('滚动后重新贴合选区，而不是留在原来的屏幕位置', async () => {
    await renderStudyPage();
    setSelectionRect(SELECTED);
    selectFirstParagraph();

    const pill = screen.getByTestId('selection-bubble');
    // 选区底部 300 → 气泡在其下方 10px
    expect(pill).toHaveStyle({ top: '310px' });

    setSelectionRect(AFTER_SCROLL);
    fireEvent.scroll(window);

    expect(screen.getByTestId('selection-bubble')).toHaveStyle({ top: '110px' });
  });

  it('选区滚出视口后气泡隐藏，滚回来再出现', async () => {
    await renderStudyPage();
    setSelectionRect(SELECTED);
    selectFirstParagraph();
    expect(screen.getByTestId('selection-bubble')).toBeInTheDocument();

    setSelectionRect(OFF_SCREEN);
    fireEvent.scroll(window);
    expect(screen.queryByTestId('selection-bubble')).toBeNull();

    setSelectionRect(AFTER_SCROLL);
    fireEvent.scroll(window);
    expect(screen.getByTestId('selection-bubble')).toBeInTheDocument();
  });

  it('浮层打开后选区滚出视口，浮层留在原地而不是跳到屏幕边缘', async () => {
    const user = userEvent.setup();
    await renderStudyPage();
    setSelectionRect(SELECTED);
    selectFirstParagraph();

    await user.click(screen.getByTestId('selection-bubble'));
    const panel = await screen.findByTestId('selection-panel');
    const before = panel.style.top;

    setSelectionRect(OFF_SCREEN);
    fireEvent.scroll(window);

    // 读答案读到一半让浮层跳到边缘，比不跟随更烦人
    expect(screen.getByTestId('selection-panel')).toBeInTheDocument();
    expect(screen.getByTestId('selection-panel').style.top).toBe(before);
  });
});
