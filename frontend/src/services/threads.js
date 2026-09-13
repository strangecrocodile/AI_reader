/**
 * 演示模式的追问线程存储：与后端 `/api/threads` 返回结构一致。
 * 接后端时这些函数不会被调用（见 services/api.js 的 useBackend 分支）。
 *
 * 数据结构：{ id, bookId, chapterId, anchorId, selectedText, title, createdAt, updatedAt,
 *            messages: [{ id, role, text, sources, sourceDetails, scope, createdAt }] }
 */
const THREADS_KEY = 'ai_reader.threads';
const TITLE_CHARS = 24;
const SELECTED_CHARS = 1000;

function readAll() {
  try {
    const parsed = JSON.parse(localStorage.getItem(THREADS_KEY) || '[]');
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeAll(threads) {
  localStorage.setItem(THREADS_KEY, JSON.stringify(threads));
}

function clip(text) {
  const value = String(text || '').trim().replace(/\s+/g, ' ');
  if (!value) return '';
  return value.length <= TITLE_CHARS ? value : `${value.slice(0, TITLE_CHARS)}…`;
}

function withTitle(thread) {
  const firstQuestion = (thread.messages ?? []).find((message) => message.role === 'user');
  return {
    ...thread,
    messages: thread.messages ?? [],
    title: clip(thread.selectedText) || clip(firstQuestion?.text) || '追问线程',
  };
}

function now() {
  return new Date().toISOString();
}

/** 本章的线程列表（最近追问的在前）。 */
export function listLocalThreads(bookId, chapterId) {
  return readAll()
    .filter((thread) => thread.bookId === bookId && thread.chapterId === chapterId)
    .sort((a, b) => String(b.updatedAt || '').localeCompare(String(a.updatedAt || '')))
    .map(withTitle);
}

export function createLocalThread({ bookId, chapterId, anchorId = '', selectedText = '' }) {
  const stamp = now();
  const thread = {
    id: `th-${Math.random().toString(36).slice(2, 12)}`,
    bookId,
    chapterId,
    anchorId: anchorId || '',
    selectedText: String(selectedText || '').slice(0, SELECTED_CHARS),
    createdAt: stamp,
    updatedAt: stamp,
    messages: [],
  };
  writeAll([...readAll(), thread]);
  return withTitle(thread);
}

export function getLocalThread(threadId) {
  const thread = readAll().find((item) => item.id === threadId);
  return thread ? withTitle(thread) : null;
}

/** 追加一条消息，返回更新后的线程。 */
export function appendLocalMessage(threadId, message) {
  const threads = readAll();
  const index = threads.findIndex((item) => item.id === threadId);
  if (index < 0) return null;
  const stamp = now();
  const messages = threads[index].messages ?? [];
  const updated = {
    ...threads[index],
    updatedAt: stamp,
    messages: [
      ...messages,
      {
        id: `${threadId}-m${messages.length + 1}`,
        createdAt: stamp,
        sources: [],
        sourceDetails: [],
        scope: '',
        ...message,
      },
    ],
  };
  threads[index] = updated;
  writeAll(threads);
  return withTitle(updated);
}

export function deleteLocalThread(threadId) {
  writeAll(readAll().filter((thread) => thread.id !== threadId));
}
