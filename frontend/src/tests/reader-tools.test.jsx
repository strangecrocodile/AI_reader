import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import App from '../App.jsx';
import { api } from '../services/api.js';
import { BookProvider } from '../state/BookContext.jsx';
import { ToastProvider } from '../state/ToastContext.jsx';

/**
 * 右侧边栏的阅读工具（翻译 / 总结）。
 *
 * 这些用例盯的是「工具面板和读者眼前的东西对不对得上」：
 * 面板能打开、范围说得清（选中原文 / 本页 / 本章）、流式结果逐段落到位、
 * 工具产出照样能回到原文核对；以及**没有模型时不编造**这一条。
 *
 * 演示模式（默认）起的是本地假流，与后端 SSE 共用同一套回调契约，
 * 所以这里测的接线在连上后端时同样成立。
 */

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

function renderApp(entry = '/study/calc7/ch2') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <BookProvider>
        <ToastProvider>
          <App />
        </ToastProvider>
      </BookProvider>
    </MemoryRouter>,
  );
}

async function openChapter(user) {
  renderApp();
  await screen.findByTestId('paper');
  return user;
}

/** 拖选第一段原文（与划词气泡用的是同一套选区），返回选中的文字。 */
async function selectFirstParagraph(user) {
  const paper = screen.getByTestId('paper');
  const span = paper.querySelector('.source');
  const range = document.createRange();
  range.selectNodeContents(span);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
  const { fireEvent } = await import('@testing-library/react');
  fireEvent.mouseUp(paper);
  return span.textContent;
}

describe('侧栏工具：入口与结构', () => {
  it('右侧边栏把三件阅读工具和讲解放在同一行工具里', async () => {
    const user = userEvent.setup();
    await openChapter(user);

    for (const name of ['AI 讲解', '知识点大纲', '追问', '翻译', '总结']) {
      expect(screen.getByRole('tab', { name })).toBeInTheDocument();
    }
  });

  it('提问会自动切到「追问」页——回答落在那一页，不切过去就像没反应', async () => {
    const user = userEvent.setup();
    await openChapter(user);
    await user.click(screen.getByRole('tab', { name: '翻译' }));

    await user.type(screen.getByLabelText('提问输入框'), '这段想表达什么？');
    await user.click(screen.getByRole('button', { name: '提问' }));

    expect(screen.getByRole('tab', { name: '追问' })).toHaveClass('active');
    await screen.findByTestId('answer', undefined, { timeout: 3000 });
  });

  it('工具切换不会把提问入口藏起来：在翻译页也能直接提问', async () => {
    const user = userEvent.setup();
    await openChapter(user);
    await user.click(screen.getByRole('tab', { name: '翻译' }));

    expect(screen.getByTestId('translate-tool')).toBeInTheDocument();
    // 底部输入框常驻：用户不该为了问一句话先切回某一页
    expect(screen.getByLabelText('提问输入框')).toBeInTheDocument();
  });
});

describe('侧栏工具：AI 翻译', () => {
  it('没有选中原文时默认译「本页」，并说清是哪一页', async () => {
    const user = userEvent.setup();
    await openChapter(user);
    await user.click(screen.getByRole('tab', { name: '翻译' }));

    const tool = screen.getByTestId('translate-tool');
    // 演示数据的章节首页是第 47 页（data/books.js）
    expect(tool).toHaveTextContent(/本页（第 \d+ 页）/);
    expect(screen.getByRole('button', { name: '选中原文' })).toBeDisabled();
  });

  it('译不出来时如实说明并列出原文，而不是编一段「像译文」的中文', async () => {
    const user = userEvent.setup();
    await openChapter(user);
    await user.click(screen.getByRole('tab', { name: '翻译' }));
    await user.click(screen.getByRole('button', { name: /本页（第 \d+ 页）/ }));

    expect(await screen.findByText(/演示模式没有接入模型，无法翻译/)).toBeInTheDocument();
    // 原文照常给出来对照（译文区为空，而不是编出来的中文）
    const results = await screen.findByTestId('translate-results');
    expect(results).toHaveTextContent(/比值/);
    const texts = screen.getAllByTestId('translate-text');
    expect(texts.every((node) => node.textContent.trim() === '')).toBe(true);
  });

  it('有选中原文时可以只译那一段', async () => {
    const user = userEvent.setup();
    await openChapter(user);
    const selected = await selectFirstParagraph(user);
    await user.click(screen.getByRole('tab', { name: '翻译' }));

    const scopeButton = screen.getByRole('button', { name: '选中原文' });
    expect(scopeButton).toBeEnabled();
    await user.click(scopeButton);

    const results = await screen.findByTestId('translate-results');
    // 只译选中那段：结果里只有一条，且原文就是刚才选的那句
    expect(results.querySelectorAll('.translate-pair')).toHaveLength(1);
    expect(results).toHaveTextContent(selected.slice(0, 12));
  });

  it('语言可以指定，且会显示当前方向', async () => {
    const user = userEvent.setup();
    const translateSpy = vi.spyOn(api, 'translateStream').mockImplementation(async (params, handlers) => {
      handlers.onMeta?.({ scope: 'page', target: params.target, page: 47, paragraphs: [] });
      handlers.onDone?.({ scope: 'page', target: params.target, translations: [], notice: '' });
    });
    await openChapter(user);
    await user.click(screen.getByRole('tab', { name: '翻译' }));

    await user.click(screen.getByRole('button', { name: '英文' }));

    await waitFor(() => expect(translateSpy).toHaveBeenCalled());
    expect(translateSpy.mock.calls[0][0].target).toBe('en');
  });
});

describe('侧栏工具：AI 总结', () => {
  it('默认总结整章，流式写入面板并标明来源', async () => {
    const user = userEvent.setup();
    await openChapter(user);
    await user.click(screen.getByRole('tab', { name: '总结' }));
    await user.click(screen.getByRole('button', { name: '本章' }));

    const body = await screen.findByTestId('summary-body', undefined, { timeout: 3000 });
    await waitFor(() => expect(body).toHaveTextContent(/段/), { timeout: 3000 });
    // 演示模式是规则摘要，必须自报家门
    expect(await screen.findByText(/规则摘要/, undefined, { timeout: 4000 })).toBeInTheDocument();
  });

  it('只总结选中的那段时带上它的原文依据', async () => {
    const user = userEvent.setup();
    await openChapter(user);
    await selectFirstParagraph(user);
    await user.click(screen.getByRole('tab', { name: '总结' }));

    const scopeButton = screen.getByRole('button', { name: '选中原文' });
    expect(scopeButton).toBeEnabled();
    await user.click(scopeButton);

    expect(await screen.findByTestId('summary-body', undefined, { timeout: 3000 })).toBeInTheDocument();
  });

  it('换章后展示后端缓存下来的总结，不必再生成一遍', async () => {
    const user = userEvent.setup();
    vi.spyOn(api, 'fetchChapterSummary').mockResolvedValue({
      summary: '本章讲导数的定义与几何意义。\n- 导数即切线斜率 [1]',
      sources: ['source-rate'],
      sourceDetails: [{ id: 'source-rate', page: 47, text: '比值 Δy / Δx 的极限存在' }],
      cached: true,
    });

    await openChapter(user);
    await user.click(screen.getByRole('tab', { name: '总结' }));

    expect(await screen.findByText(/导数的定义与几何意义/)).toBeInTheDocument();
    expect(screen.getByText('已缓存')).toBeInTheDocument();
    // 缓存结果同样能回跳原文核对
    expect(screen.getByTestId('summary-sources')).toHaveTextContent(/第 47 页/);
  });

  it('生成失败时给出原因，而不是一个永远转圈的「正在生成」', async () => {
    const user = userEvent.setup();
    vi.spyOn(api, 'summarizeStream').mockRejectedValue(new Error('总结失败（500）'));
    await openChapter(user);
    await user.click(screen.getByRole('tab', { name: '总结' }));
    await user.click(screen.getByRole('button', { name: '本章' }));

    expect(await screen.findByText('总结失败（500）')).toBeInTheDocument();
  });

  it('分块生成时显示进度（长章要跑好几块，不能只转圈）', async () => {
    const user = userEvent.setup();
    vi.spyOn(api, 'summarizeStream').mockImplementation(async (_params, handlers) => {
      handlers.onMeta?.({ scope: 'chapter', chunkCount: 3, paragraphCount: 24, totalParagraphs: 24, pages: [16, 40] });
      handlers.onProgress?.({ chunk: 1, chunkCount: 3 });
      handlers.onDelta?.('先讲极限。');
      handlers.onDone?.({
        scope: 'chapter',
        summary: '先讲极限。',
        sources: [],
        sourceDetails: [],
        notice: '',
      });
    });
    await openChapter(user);
    await user.click(screen.getByRole('tab', { name: '总结' }));

    // 点「本章」后立刻应看到进度（不 await 结果）
    await user.click(screen.getByRole('button', { name: '本章' }));
    expect(await screen.findByText(/覆盖第 16–40 页/)).toBeInTheDocument();
  });
});
