import { books, studyContents } from '../data/books.js';
import { knowledgeFor } from '../data/knowledge.js';
import { answerFor } from './mockAnswers.js';

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

  /** 记录进入章节或完成问答等学习事件。 */
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
};

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
