import { books, studyContents } from '../data/books.js';
import { knowledgeFor } from '../data/knowledge.js';
import { answerFor } from './mockAnswers.js';
import { recordLocalEvent } from './progress.js';
import { appendLocalMessage, createLocalThread, deleteLocalThread, listLocalThreads } from './threads.js';

/**
 * API 接口层：页面组件只依赖本模块。
 *
 * 两种模式（按 apiBase 自动切换）：
 * - 后端模式：设置了 VITE_API_BASE_URL（或运行时调用 configureApiBase）时，
 *   走真实 REST 接口（FastAPI 后端，见 backend/app/routers）。
 * - 演示模式：未配置时使用内置 mock 数据，交互链路不变。
 */

const configuredApiBase = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
// 测试必须使用确定性的演示数据，不能因为本机 .env 配置而访问外部服务。
let apiBase = import.meta.env.MODE === 'test' ? '' : configuredApiBase;
const PROGRESS_KEY = 'ai_reader.chapterProgress';

/** 运行时切换后端地址（也用于测试）；传空字符串回到演示模式。 */
export function configureApiBase(url) {
  apiBase = url ? String(url).replace(/\/$/, '') : '';
}

const useBackend = () => apiBase !== '';

async function request(path, options = {}) {
  const res = await fetch(apiBase + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${path}`);
  }
  return res.json();
}

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export const api = {
  /** 获取教材列表（含章节与学习计划）。 */
  async fetchBooks() {
    if (useBackend()) return request('/api/books');
    await delay(200); // 模拟网络耗时
    return books.map((b) => withLocalProgress(b));
  },

  /** 上传文本型 PDF，后端解析目录、段落与锚点后返回教材元信息。 */
  async uploadBook(file, title = '') {
    if (!useBackend()) {
      throw new Error('演示模式不支持真实 PDF 上传，请先连接 FastAPI 后端');
    }
    const form = new FormData();
    form.append('file', file);
    if (title.trim()) form.append('title', title.trim());
    const res = await fetch(`${apiBase}/api/books`, { method: 'POST', body: form });
    if (!res.ok) {
      let detail = `上传失败（${res.status}）`;
      try {
        const data = await res.json();
        if (data.detail) detail = data.detail;
      } catch {
        // 保留通用错误文案
      }
      throw new Error(detail);
    }
    return res.json();
  },

  /**
   * 后端当前能收哪些格式（`.`doc` 依赖可选的 LibreOffice）。
   *
   * 拿不到时返回 null：前端用内置的默认提示，不至于因为一个探测请求失败就
   * 让上传功能整个不可用。
   */
  async fetchCapabilities() {
    if (!useBackend()) return null;
    try {
      return await request('/api/capabilities');
    } catch {
      return null;
    }
  },

  /**
   * 原文件的下载地址；这本教材没有留存原文件时返回空串。
   *
   * 只给 URL 而不代下载：让浏览器用自己的下载能力（进度、断点、另存为），
   * 也避免把整本书读进内存。
   */
  sourceUrl(book) {
    if (!book?.hasSource) return '';
    if (!useBackend()) return ''; // 演示模式没有真实原文件
    return `${apiBase}/api/books/${book.id}/source`;
  },

  /** 获取单本教材；不存在返回 null。 */
  async fetchBook(bookId) {
    if (useBackend()) {
      try {
        return await request(`/api/books/${bookId}`);
      } catch {
        return null;
      }
    }
    await delay(150);
    const book = books.find((b) => b.id === bookId);
    return book ? withLocalProgress(book) : null;
  },

  /**
   * 获取章节学习内容（原文段落 + 备课讲解 + 知识点大纲）。
   * 章节暂未准备内容时返回 null。
   */
  async fetchStudyContent(bookId, chapterId) {
    if (useBackend()) {
      try {
        return await request(`/api/books/${bookId}/chapters/${chapterId}`);
      } catch {
        return null;
      }
    }
    await delay(200);
    const content = studyContents[bookId]?.[chapterId];
    return content ? structuredClone(content) : null;
  },

  /** 获取知识点卡片与关系图谱数据。 */
  async fetchKnowledge(bookId) {
    if (useBackend()) {
      try {
        return await request(`/api/books/${bookId}/knowledge`);
      } catch {
        return null;
      }
    }
    await delay(160);
    return structuredClone(knowledgeFor(bookId, readProgress(bookId)));
  },

  /** 记录进入章节或完成问答等学习事件（手动覆盖进度，正常学习请走 recordLearningEvent）。 */
  async markChapterProgress({ bookId, chapterId, status, mastery }) {
    if (useBackend()) {
      const data = await request(`/api/books/${bookId}/chapters/${chapterId}/progress`, {
        method: 'POST',
        body: JSON.stringify({ status, mastery }),
      });
      return data;
    }
    const progress = readAllProgress();
    const previous = progress[bookId]?.[chapterId];
    progress[bookId] ??= {};
    progress[bookId][chapterId] = {
      status,
      mastery: Math.max(previous?.mastery ?? 0, mastery),
    };
    localStorage.setItem(PROGRESS_KEY, JSON.stringify(progress));
    return progress[bookId][chapterId];
  },

  /**
   * 上报一次学习事件（open / read / ask / complete / quiz），返回重算后的掌握度。
   * 掌握度由事件算出，前端不再自己编数字；演示模式用同一套公式在本地计算。
   * @returns {Promise<{status: string, mastery: number, computed: number, breakdown: object[], signals: object}>}
   */
  async recordLearningEvent({ bookId, chapterId, kind, anchorIds, question, correct }) {
    if (useBackend()) {
      return request(`/api/books/${bookId}/chapters/${chapterId}/events`, {
        method: 'POST',
        body: JSON.stringify({
          kind,
          anchorIds: anchorIds ?? [],
          question: question ?? null,
          correct: correct ?? null,
        }),
      });
    }
    const result = recordLocalEvent(bookId, chapterId, { kind, anchorIds, question, correct });
    const progress = readAllProgress();
    progress[bookId] ??= {};
    const previous = progress[bookId][chapterId];
    progress[bookId][chapterId] = {
      status: previous?.status === 'learned' ? 'learned' : result.status,
      mastery: Math.max(previous?.mastery ?? 0, result.mastery),
    };
    localStorage.setItem(PROGRESS_KEY, JSON.stringify(progress));
    return {
      ...result,
      status: progress[bookId][chapterId].status,
      mastery: progress[bookId][chapterId].mastery,
    };
  },

  /**
   * 向 AI 讲师提问，返回回答与所依据的教材锚点。
   * @param {{ question: string, selectedText?: string, bookId: string, chapterId: string }} params
   * @returns {Promise<{ text: string, sources: string[] }>}
   */
  async ask({ question, selectedText, bookId, chapterId }) {
    if (useBackend()) {
      const data = await request('/api/ask', {
        method: 'POST',
        body: JSON.stringify({ question, bookId, chapterId, selectedText: selectedText || null }),
      });
      return { text: data.answer, sources: data.sources, sourceDetails: data.sourceDetails || [] };
    }
    await delay(350); // 模拟模型推理耗时
    return answerFor(question, { selectedText });
  },

  /**
   * 流式提问：后端走 SSE（`POST /api/ask/stream`），演示模式在本地分块模拟，
   * 两条路径都通过 onDelta/onDone 回报，页面渲染逻辑只写一份。
   *
   * 带 threadId 时问答会写进该追问线程（后端持久化 / 演示模式写 localStorage）。
   *
   * @param {{ question: string, selectedText?: string, bookId: string, chapterId: string, threadId?: string }} params
   * @param {{ onDelta?: (text: string) => void, onDone?: (payload: object) => void, signal?: AbortSignal }} handlers
   */
  async askStream({ question, selectedText, bookId, chapterId, threadId }, handlers = {}) {
    const { onDelta, onDone, signal } = handlers;
    if (!useBackend()) {
      if (threadId) appendLocalMessage(threadId, { role: 'user', text: question });
      const result = answerFor(question, { selectedText });
      for (const chunk of chunkText(result.text)) {
        if (signal?.aborted) return;
        onDelta?.(chunk);
        await delay(DEMO_STREAM_INTERVAL);
      }
      const payload = {
        answer: result.text,
        sources: result.sources ?? [],
        sourceDetails: [],
        scope: 'chapter',
        threadId: threadId ?? null,
      };
      if (threadId) {
        appendLocalMessage(threadId, {
          role: 'assistant',
          text: payload.answer,
          sources: payload.sources,
        });
      }
      onDone?.(payload);
      return;
    }

    const res = await fetch(`${apiBase}/api/ask/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({
        question,
        bookId,
        chapterId,
        selectedText: selectedText || null,
        threadId: threadId || null,
      }),
      signal,
    });
    if (!res.ok || !res.body) {
      throw new Error(`API ${res.status}: /api/ask/stream`);
    }
    await readEventStream(res.body, { onDelta, onDone });
  },

  /** 本章的追问线程列表（最近追问的在前）。 */
  async fetchThreads(bookId, chapterId) {
    if (useBackend()) {
      return request(`/api/books/${bookId}/chapters/${chapterId}/threads`);
    }
    await delay(80);
    return listLocalThreads(bookId, chapterId);
  },

  /** 为一段选中原文新建追问线程（划词气泡打开时调用）。 */
  async createThread({ bookId, chapterId, anchorId = '', selectedText = '' }) {
    if (useBackend()) {
      return request('/api/threads', {
        method: 'POST',
        body: JSON.stringify({ bookId, chapterId, anchorId, selectedText }),
      });
    }
    return createLocalThread({ bookId, chapterId, anchorId, selectedText });
  },

  /** 删除追问线程。 */
  async deleteThread(threadId) {
    if (useBackend()) {
      const res = await fetch(`${apiBase}/api/threads/${threadId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(`API ${res.status}: /api/threads/${threadId}`);
      return;
    }
    deleteLocalThread(threadId);
  },
};

const DEMO_STREAM_CHUNK = 8;
const DEMO_STREAM_INTERVAL = 45;

function chunkText(text, size = DEMO_STREAM_CHUNK) {
  const chunks = [];
  for (let i = 0; i < text.length; i += size) chunks.push(text.slice(i, i + size));
  return chunks.length ? chunks : [''];
}

/** 解析一个 SSE 帧（`event: x\ndata: {...}`）→ {event, data}。 */
function parseEventFrame(frame) {
  let event = 'message';
  let data = '';
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) data += line.slice(5).trim();
  }
  if (!data) return null;
  try {
    return { event, data: JSON.parse(data) };
  } catch {
    return null;
  }
}

/** 读取 fetch 的 SSE 流：meta → delta* → done（或 error）。 */
async function readEventStream(body, { onDelta, onDone } = {}) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split('\n\n');
      buffer = frames.pop() ?? '';
      for (const frame of frames) {
        const parsed = parseEventFrame(frame);
        if (!parsed) continue;
        if (parsed.event === 'delta') onDelta?.(parsed.data.text ?? '');
        else if (parsed.event === 'done') onDone?.(parsed.data);
        else if (parsed.event === 'error') throw new Error(parsed.data.message || '流式回答失败');
      }
    }
  } finally {
    reader.cancel?.().catch(() => {});
  }
}

function readAllProgress() {
  try {
    return JSON.parse(localStorage.getItem(PROGRESS_KEY) || '{}');
  } catch {
    return {};
  }
}

function readProgress(bookId) {
  return readAllProgress()[bookId] ?? {};
}

function withLocalProgress(b) {
  const progress = readProgress(b.id);
  if (Object.keys(progress).length === 0) {
    return {
      ...b,
      chapters: b.chapters.map((chapter) => ({ ...chapter })),
    };
  }
  const chapters = b.chapters.map((chapter, index) => {
    const saved = progress[chapter.id];
    if (!saved) return { ...chapter };
    return {
      ...chapter,
      status: saved.status,
      meta: saved.status === 'learned' ? '已完成' : '正在学习',
      progressPct: saved.mastery,
      isToday: index === 0 && saved.status !== 'learned',
    };
  });
  const mastery =
    chapters.reduce((sum, chapter) => sum + (progress[chapter.id]?.mastery ?? 0), 0) /
    Math.max(chapters.length, 1);
  return {
    ...b,
    progressText: `${Math.round(mastery)}% 已完成`,
    chapters,
  };
}
