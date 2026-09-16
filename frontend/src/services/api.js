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

/** 上传体积上限，与后端 `services/ingest.py` 的 `MAX_UPLOAD_BYTES` 保持一致。
 *  前端先拦一道只是为了省掉一次几百 MB 的无用上传，真正的把关在后端。 */
export const MAX_UPLOAD_BYTES = 200 * 1024 * 1024;

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

/**
 * 从失败响应里取后端的 `detail` 文案（中文、能直接给用户看）。
 * 后端不可达或返回的不是 JSON 时退回通用文案——上传/删除这类操作用户
 * 最需要知道的是「为什么不行」，所以这个兜底宁可粗糙也不能是空的。
 */
async function failureDetail(res, fallback) {
  try {
    const data = await res.json();
    if (data.detail) return data.detail;
  } catch {
    // 响应体不是 JSON，用兜底文案
  }
  return fallback;
}

export const api = {
  /** 获取教材列表（含章节与学习计划）。 */
  async fetchBooks() {
    if (useBackend()) return request('/api/books');
    await delay(200); // 模拟网络耗时
    return books.map((b) => withLocalProgress(b));
  },

  /**
   * 上传教材。后端按「有没有文本层」分两条路，所以返回值也分两种：
   *
   * - `{ kind: 'book', book }` —— 常规解析（201），`book` 就是教材元信息，可以立即用；
   * - `{ kind: 'ocr', task }` —— 后端判定这是扫描件（202），已经把它转成异步识别任务，
   *   此刻**还没有教材**。要拿 `task.id` 去 `fetchOcrTask` 轮询，识别完才有书。
   *
   * 用显式的 `kind` 而不是「有没有 task 字段」来区分，是为了让调用方的分支
   * 在前端就写死，语义上骗不了人。
   */
  async uploadBook(file, title = '') {
    if (!useBackend()) {
      throw new Error('演示模式不支持真实 PDF 上传，请先连接 FastAPI 后端');
    }
    const form = new FormData();
    form.append('file', file);
    if (title.trim()) form.append('title', title.trim());
    const res = await fetch(`${apiBase}/api/books`, { method: 'POST', body: form });
    if (!res.ok) {
      throw new Error(await failureDetail(res, `上传失败（${res.status}）`));
    }
    const body = await res.json();
    return res.status === 202 ? { kind: 'ocr', task: body.task } : { kind: 'book', book: body };
  },

  /**
   * 删除教材及其全部下游数据（章节、段落、锚点、讲解、学习进度、追问线程）。
   *
   * **不可恢复**，也是唯一会丢弃 OCR 结果的操作——扫描件删掉就得重新识别几十分钟。
   * 所以确认这一步由调用方负责，这里只负责把后端的话原样带回去。
   */
  async deleteBook(bookId) {
    if (!useBackend()) {
      throw new Error('演示模式不支持删除教材，请先连接 FastAPI 后端');
    }
    const res = await fetch(`${apiBase}/api/books/${bookId}`, { method: 'DELETE' });
    if (!res.ok) {
      throw new Error(await failureDetail(res, `删除失败（${res.status}）`));
    }
  },

  /**
   * 查询扫描件识别任务的进度。
   *
   * 任务不存在时返回 `null`——那意味着后端重启过（任务状态落在 SQLite 里还在，
   * 但跑识别的线程随进程没了），调用方据此提示「重新上传」，而不是干转圈。
   * 网络异常照常抛出，让调用方当作「这一轮没问到」重试——把 404 和断网混为一谈，
   * 会让一次网络抖动就报「任务已中断」。
   */
  async fetchOcrTask(taskId) {
    const res = await fetch(`${apiBase}/api/ocr/tasks/${taskId}`);
    if (res.status === 404) return null;
    if (!res.ok) throw new Error(`API ${res.status}: /api/ocr/tasks/${taskId}`);
    return res.json();
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
