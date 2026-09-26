import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import App from '../App.jsx';
import { api } from '../services/api.js';
import { BookProvider } from '../state/BookContext.jsx';
import { ToastProvider } from '../state/ToastContext.jsx';

/**
 * 笔记：把「我读到这里想到了什么」留在原文上。
 *
 * 判据的重点是**绑定关系**：笔记认的是段落锚点（和溯源问答同一套坐标），
 * 所以「回到这条笔记对应的原文」跳得准，段落上的记号也点得对。
 * 另外，保存失败不能把用户刚写的东西清掉——那是最气人的一种失败。
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

async function startNote(user) {
  await screen.findByTestId('paper');
  selectFirstParagraph();
  await user.click(await screen.findByTestId('note-start'));
  return screen.findByLabelText('笔记内容');
}

describe('笔记', () => {
  it('选中原文后可以记一条笔记，并带上那段原文与锚点', async () => {
    const createNote = vi.spyOn(api, 'createNote').mockImplementation(async (payload) => ({
      id: 'n1',
      ...payload,
      createdAt: '2026-01-01T00:00:00+00:00',
      updatedAt: '2026-01-01T00:00:00+00:00',
    }));
    vi.spyOn(api, 'fetchNotes').mockResolvedValue([]);
    const user = userEvent.setup();

    renderApp();
    const box = await startNote(user);
    await user.type(box, '这里和上一章的映射一起看');
    await user.click(screen.getByRole('button', { name: '保存笔记' }));

    await waitFor(() => expect(createNote).toHaveBeenCalled());
    const payload = createNote.mock.calls[0][0];
    expect(payload.body).toBe('这里和上一章的映射一起看');
    // 绑定的是锚点而不是页码：页码会随版本变化，锚点不会
    expect(payload.anchorId).toBeTruthy();
    expect(payload.quotedText).toBeTruthy();
    expect(await screen.findByText('已记下这条笔记')).toBeInTheDocument();
  });

  it('记完笔记后章节里能看到它，并给对应段落点上记号', async () => {
    vi.spyOn(api, 'createNote').mockResolvedValue({
      id: 'n1',
      bookId: 'calc7',
      chapterId: 'ch2',
      anchorId: 'source-rate',
      quotedText: '一个量相对于另一个量的变化率',
      body: '记住这条',
      createdAt: '2026-01-01T00:00:00+00:00',
      updatedAt: '2026-01-01T00:00:00+00:00',
    });
    vi.spyOn(api, 'fetchNotes').mockResolvedValue([]);
    const user = userEvent.setup();

    renderApp();
    const box = await startNote(user);
    await user.type(box, '记住这条');
    await user.click(screen.getByRole('button', { name: '保存笔记' }));

    expect(await screen.findByTestId('note-list')).toBeInTheDocument();
    expect(screen.getByTestId('note-n1')).toHaveTextContent('记住这条');
    // 段落上的记号：让用户扫一眼就知道书里哪儿有自己的笔记
    expect(await screen.findByTestId('note-mark-source-rate')).toBeInTheDocument();
  });

  it('打开章节时会载入已有笔记', async () => {
    vi.spyOn(api, 'fetchNotes').mockResolvedValue([
      {
        id: 'old',
        bookId: 'calc7',
        chapterId: 'ch2',
        anchorId: 'source-rate',
        quotedText: '变化率',
        body: '上次记的',
        createdAt: '2026-01-01T00:00:00+00:00',
        updatedAt: '2026-01-01T00:00:00+00:00',
      },
    ]);

    renderApp();

    expect(await screen.findByTestId('note-old')).toHaveTextContent('上次记的');
    expect(screen.getByTestId('note-mark-source-rate')).toBeInTheDocument();
  });

  it('保存失败时把原因说出来，且不清空用户写的内容', async () => {
    vi.spyOn(api, 'createNote').mockRejectedValue(new Error('笔记内容不能为空'));
    vi.spyOn(api, 'fetchNotes').mockResolvedValue([]);
    const user = userEvent.setup();

    renderApp();
    const box = await startNote(user);
    await user.type(box, '写了半天的一句');
    await user.click(screen.getByRole('button', { name: '保存笔记' }));

    expect(await screen.findByText('笔记内容不能为空')).toBeInTheDocument();
    // 草稿还在：失败还把用户写的东西抹掉，是最气人的那种失败
    expect(screen.getByLabelText('笔记内容')).toHaveValue('写了半天的一句');
  });

  it('点笔记会回到它对应的原文', async () => {
    vi.spyOn(api, 'fetchNotes').mockResolvedValue([
      {
        id: 'old',
        bookId: 'calc7',
        chapterId: 'ch2',
        anchorId: 'source-rate',
        quotedText: '变化率',
        body: '上次记的',
        createdAt: '2026-01-01T00:00:00+00:00',
        updatedAt: '2026-01-01T00:00:00+00:00',
      },
    ]);
    const user = userEvent.setup();

    renderApp();
    await user.click(await screen.findByTestId('note-old'));

    expect(await screen.findByText('已定位到这条笔记对应的原文')).toBeInTheDocument();
  });

  it('可以改笔记正文', async () => {
    vi.spyOn(api, 'fetchNotes').mockResolvedValue([
      {
        id: 'old',
        bookId: 'calc7',
        chapterId: 'ch2',
        anchorId: 'source-rate',
        quotedText: '变化率',
        body: '原来的内容',
        createdAt: '2026-01-01T00:00:00+00:00',
        updatedAt: '2026-01-01T00:00:00+00:00',
      },
    ]);
    const updateNote = vi.spyOn(api, 'updateNote').mockImplementation(async (id, body) => ({
      id,
      bookId: 'calc7',
      chapterId: 'ch2',
      anchorId: 'source-rate',
      quotedText: '变化率',
      body,
      createdAt: '2026-01-01T00:00:00+00:00',
      updatedAt: '2026-01-01T00:00:00+00:00',
    }));
    const user = userEvent.setup();

    renderApp();
    await user.click(await screen.findByRole('button', { name: /编辑笔记/ }));
    const box = screen.getByLabelText('编辑笔记内容');
    await user.clear(box);
    await user.type(box, '改好了');
    await user.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => expect(updateNote).toHaveBeenCalledWith('old', '改好了'));
  });

  it('可以删笔记，删完列表里就没有了', async () => {
    vi.spyOn(api, 'fetchNotes').mockResolvedValue([
      {
        id: 'old',
        bookId: 'calc7',
        chapterId: 'ch2',
        anchorId: 'source-rate',
        quotedText: '变化率',
        body: '要删掉的',
        createdAt: '2026-01-01T00:00:00+00:00',
        updatedAt: '2026-01-01T00:00:00+00:00',
      },
    ]);
    const deleteNote = vi.spyOn(api, 'deleteNote').mockResolvedValue(undefined);
    const user = userEvent.setup();

    renderApp();
    await user.click(await screen.findByRole('button', { name: /删除笔记/ }));

    await waitFor(() => expect(deleteNote).toHaveBeenCalledWith('old'));
    await waitFor(() => expect(screen.queryByTestId('note-list')).toBeNull());
  });
});
