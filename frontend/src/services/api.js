import { books, studyContents } from '../data/books.js';
import { answerFor } from './mockAnswers.js';

/**
 * API 接口层：页面组件只依赖本模块。
 *
 * 两种模式（按 apiBase 自动切换）：
 * - 后端模式：设置了 VITE_API_BASE_URL（或运行时调用 configureApiBase）时，
 *   走真实 REST 接口（FastAPI 后端，见 backend/app/routers）。
 * - 演示模式：未配置时使用内置 mock 数据，交互链路不变。
 */

let apiBase = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');

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
    return books.map((b) => ({ ...b, chapters: b.chapters.map((c) => ({ ...c })) }));
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
    return book ? { ...book } : null;
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
      return { text: data.answer, sources: data.sources };
    }
    await delay(350); // 模拟模型推理耗时
    return answerFor(question, { selectedText });
  },
};
