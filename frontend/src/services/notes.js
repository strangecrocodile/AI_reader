/**
 * 演示模式的笔记存储：与后端 `/api/notes` 返回结构一致。
 * 接后端时这些函数不会被调用（见 services/api.js 的 useBackend 分支）。
 *
 * 数据结构：{ id, bookId, chapterId, anchorId, quotedText, body, createdAt, updatedAt }
 */
const NOTES_KEY = 'ai_reader.notes';
const QUOTE_CHARS = 500;

function readAll() {
  try {
    const parsed = JSON.parse(localStorage.getItem(NOTES_KEY) || '[]');
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeAll(notes) {
  try {
    localStorage.setItem(NOTES_KEY, JSON.stringify(notes));
  } catch {
    // 隐私模式下写不进去：本次会话内仍可显示，只是刷新后丢，不值得把界面搞崩
  }
}

function now() {
  return new Date().toISOString();
}

export function listLocalNotes(bookId, chapterId) {
  return readAll()
    .filter((note) => note.bookId === bookId && note.chapterId === chapterId)
    .sort((a, b) => String(b.updatedAt || '').localeCompare(String(a.updatedAt || '')));
}

export function createLocalNote({ bookId, chapterId, anchorId = '', quotedText = '', body = '' }) {
  const stamp = now();
  const note = {
    id: `note-${Math.random().toString(36).slice(2, 12)}`,
    bookId,
    chapterId,
    anchorId: anchorId || '',
    quotedText: String(quotedText || '').slice(0, QUOTE_CHARS),
    body: String(body || '').trim(),
    createdAt: stamp,
    updatedAt: stamp,
  };
  writeAll([...readAll(), note]);
  return note;
}

export function updateLocalNote(noteId, body) {
  const notes = readAll();
  const index = notes.findIndex((note) => note.id === noteId);
  if (index < 0) return null;
  notes[index] = { ...notes[index], body: String(body || '').trim(), updatedAt: now() };
  writeAll(notes);
  return notes[index];
}

export function deleteLocalNote(noteId) {
  writeAll(readAll().filter((note) => note.id !== noteId));
}
