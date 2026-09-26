import { books, studyContents } from '../data/books.js';
import { knowledgeFor } from '../data/knowledge.js';
import { answerFor } from './mockAnswers.js';
import { recordLocalEvent } from './progress.js';
import {
  createLocalNote,
  deleteLocalNote,
  listLocalNotes,
  updateLocalNote,
} from './notes.js';
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
    // 状态码挂在 error 上：调用方常常需要区分「404 这东西不存在」与「5xx/断网，
    // 该让用户重试」。只看 message 字符串去认状态码是脆的（见 fetchStudyContent）。
    const error = new Error(`API ${res.status}: ${path}`);
    error.status = res.status;
    throw error;
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
   * 让后端重新生成这本书的学习路径（LLM + 规则回退）。
   *
   * 返回值是后端的原始计划结构，**不是**页面用的那份：展示用的 `plan`
   * （headline / sub / goal / remaining）由 `serializers._plan_to_frontend` 拼出来，
   * 只有重读教材列表才拿得到。所以调用方约定：先 await 本方法，再 `refreshBooks()`。
   */
  async regeneratePlan(bookId) {
    if (!useBackend()) {
      throw new Error('演示模式不支持重新规划学习路径，请先连接 FastAPI 后端');
    }
    return request(`/api/books/${bookId}/plan`, { method: 'POST' });
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

  /**
   * 教材 Markdown 导出的地址；演示模式下没有后端可导出。
   *
   * 与「下载原文件」不是一回事：导出是**从库里现渲染**的（`backend/app/services/export.py`），
   * 每个段落带 `<!-- page: N -->`，所以只要这本书在库里就有——不需要留存过原文件。
   * 老教材（该功能上线前导入、没有原文件）也照样能导出。
   */
  markdownUrl(book) {
    if (!book?.id) return '';
    if (!useBackend()) return ''; // 演示模式的数据是前端内置的，没有可导出的库
    return `${apiBase}/api/books/${book.id}/markdown`;
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
   *
   * 返回值有三种含义，**页面必须分得开**：
   * - 有内容 → 内容对象；
   * - `null` → 这一章确实没有内容（404：演示数据没覆盖，或章节已不存在）；
   * - 抛错 → 加载失败（5xx / 断网 / 超时），是**暂时性**的，用户重试有意义。
   *
   * 以前这里把两者都吞成 `null`，于是后端抖一下，真实用户会被告知「本章内容尚未准备」，
   * 而那个占位文案当时还写着「演示数据目前只包含《高等数学》2.1 导数」——一本医学教材
   * 的用户看到这句会以为自己的书根本没进去，而且页面上没有任何重试入口。
   */
  async fetchStudyContent(bookId, chapterId) {
    if (useBackend()) {
      try {
        return await request(`/api/books/${bookId}/chapters/${chapterId}`);
      } catch (error) {
        if (error.status === 404) return null;
        throw error;
      }
    }
    await delay(200);
    const content = studyContents[bookId]?.[chapterId];
    return content ? structuredClone(content) : null;
  },

  /**
   * 在整本教材里搜索，返回带锚点与章节的命中，用于「跳过去并高亮」。
   *
   * 空查询返回空列表（后端也是这个约定）：用户清空输入框不该看到报错。
   */
  async searchBook(bookId, query, limit = 20) {
    const text = String(query || '').trim();
    if (!text) return { query: '', total: 0, hits: [] };
    if (useBackend()) {
      const params = new URLSearchParams({ q: text, limit: String(limit) });
      return request(`/api/books/${bookId}/search?${params}`);
    }
    await delay(120);
    return searchDemoContent(bookId, text, limit);
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
      return {
        text: data.answer,
        sources: data.sources,
        sourceDetails: data.sourceDetails || [],
        // 拒答出口：契约恒定，两个接口都带（见后端 services/ask.py 的 `_no_evidence_result`）
        noEvidence: data.noEvidence === true,
        closest: data.closest || [],
        hint: data.hint || '',
        scope: data.scope || '',
      };
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
        // 演示模式没有后端的依据判定，恒为「有依据」，保持与真实接口同一个形状
        noEvidence: false,
        closest: [],
        hint: '',
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

  // ---------- 笔记 ----------

  /**
   * 本章笔记，最近更新的在前。
   *
   * 笔记绑的是**段落锚点**（和溯源问答同一套坐标），所以「回到这条笔记对应的原文」
   * 永远跳得准；页码会随版本与解析方式变化，锚点不会。
   */
  async fetchNotes(bookId, chapterId) {
    if (useBackend()) {
      return request(`/api/books/${bookId}/chapters/${chapterId}/notes`);
    }
    await delay(60);
    return listLocalNotes(bookId, chapterId);
  },

  /** 新建笔记。`anchorId` 为空表示整章感想（不绑定具体段落）。 */
  async createNote({ bookId, chapterId, anchorId = '', quotedText = '', body }) {
    if (useBackend()) {
      const res = await fetch(`${apiBase}/api/notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bookId, chapterId, anchorId, quotedText, body }),
      });
      if (!res.ok) throw new Error(await failureDetail(res, `记笔记失败（${res.status}）`));
      return res.json();
    }
    return createLocalNote({ bookId, chapterId, anchorId, quotedText, body });
  },

  /** 改笔记正文。锚点是笔记的身份，后端不允许改，这里也就不提供这个参数。 */
  async updateNote(noteId, body) {
    if (useBackend()) {
      const res = await fetch(`${apiBase}/api/notes/${noteId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ body }),
      });
      if (!res.ok) throw new Error(await failureDetail(res, `更新笔记失败（${res.status}）`));
      return res.json();
    }
    return updateLocalNote(noteId, body);
  },

  /** 删除笔记。 */
  async deleteNote(noteId) {
    if (useBackend()) {
      const res = await fetch(`${apiBase}/api/notes/${noteId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(`API ${res.status}: /api/notes/${noteId}`);
      return;
    }
    deleteLocalNote(noteId);
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

/**
 * 演示模式下的整本搜索：直接在前端内置的演示数据里扫一遍。
 *
 * 演示数据只有一章有正文，所以命中很少——但形状与后端完全一致，界面只有一套逻辑。
 * 演示模式什么都不返回的话，搜索结果永远为空，看起来像功能坏了。
 */
function searchDemoContent(bookId, query, limit) {
  const book = books.find((item) => item.id === bookId);
  const contents = studyContents[bookId] || {};
  const hits = [];
  const needle = query.toLowerCase();

  for (const chapter of book?.chapters ?? []) {
    const content = contents[chapter.id];
    for (const para of content?.paragraphs ?? []) {
      const anchorId = firstAnchorOf(para);
      // 没有锚点的段落定位不了——点进去也不会高亮，不如不给这条
      if (!anchorId) continue;
      const text = segmentsToText(para);
      if (!text || !text.toLowerCase().includes(needle)) continue;
      hits.push({
        anchorId,
        chapterId: chapter.id,
        chapterTitle: chapter.title,
        page: content.page ?? 1,
        text,
        kind: para.type ?? 'p',
        score: 0,
      });
      if (hits.length >= limit) return { query, total: hits.length, hits };
    }
  }
  return { query, total: hits.length, hits };
}

/** 把一个段落块拼成纯文本（演示数据里正文是片段数组）。 */
function segmentsToText(para) {
  if (para.type && para.type !== 'p') return para.caption || '';
  return (para.segs ?? [])
    .map((seg) => {
      if (typeof seg.v === 'string' && seg.v) return seg.v;
      if (Array.isArray(seg.segs)) return seg.segs.map((inner) => inner.v ?? '').join('');
      return '';
    })
    .join('');
}

/** 段落里第一个带锚点的片段 id（后端把锚点放在最外层片段上）。 */
function firstAnchorOf(para) {
  const seg = (para.segs ?? []).find((item) => item.t === 'src');
  return seg?.id ?? '';
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
