import { books, studyContents } from '../data/books.js';
import { answerFor } from './mockAnswers.js';

/**
 * API 接口层：页面组件只依赖本模块，不直接读 mock 数据。
 *
 * 接入真实后端时，仅需将各方法的 mock 实现替换为 fetch 调用，
 * 例如：fetch(`/api/books/${bookId}`) → 教材详情；
 *      POST `/api/ask` → { question, selectedText, bookId, chapterId } → { answer, sources }。
 * 返回结构保持不变，页面无需改动。
 */

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export const api = {
  /** 获取教材列表（含章节与学习计划）。 */
  async fetchBooks() {
    await delay(200); // 模拟网络耗时
    return books.map((b) => ({ ...b, chapters: b.chapters.map((c) => ({ ...c })) }));
  },

  /** 获取单本教材；不存在返回 null。 */
  async fetchBook(bookId) {
    await delay(150);
    const book = books.find((b) => b.id === bookId);
    return book ? { ...book } : null;
  },

  /**
   * 获取章节学习内容（原文段落 + 备课讲解 + 知识点大纲）。
   * 章节暂未准备内容时返回 null。
   */
  async fetchStudyContent(bookId, chapterId) {
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
    await delay(350); // 模拟模型推理耗时
    return answerFor(question, { selectedText });
  },
};
