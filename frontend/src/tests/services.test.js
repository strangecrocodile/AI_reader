import { beforeEach, describe, expect, it } from 'vitest';
import { answerFor } from '../services/mockAnswers.js';
import { api } from '../services/api.js';

beforeEach(() => {
  localStorage.clear();
});

describe('answerFor（模拟问答）', () => {
  it('含「极限」的问题返回极限讲解并引用导数定义', () => {
    const res = answerFor('为什么一定要取极限？');
    expect(res.text).toContain('极限');
    expect(res.sources).toEqual(['source-limit']);
  });

  it('含「为什么」的问题走极限讲解', () => {
    const res = answerFor('为什么这个比值叫导数？');
    expect(res.sources).toContain('source-limit');
  });

  it('普通问题返回默认讲解并引用多个锚点', () => {
    const res = answerFor('这一段想表达什么？');
    expect(res.text).toContain('Δy / Δx');
    expect(res.sources).toEqual(['source-rate', 'source-limit']);
  });
});

describe('api 接口层', () => {
  it('fetchBooks 返回教材列表', async () => {
    const list = await api.fetchBooks();
    expect(list).toHaveLength(3);
    expect(list[0].id).toBe('calc7');
    expect(list[0].chapters).toHaveLength(3);
  });

  it('fetchBook 返回单本教材，不存在返回 null', async () => {
    expect((await api.fetchBook('calc7')).title).toBe('高等数学');
    expect(await api.fetchBook('nope')).toBeNull();
  });

  it('fetchStudyContent 返回章节内容', async () => {
    const content = await api.fetchStudyContent('calc7', 'ch2');
    expect(content.heading).toBe('2.1 导数的概念');
    expect(content.paragraphs.length).toBeGreaterThan(0);
    expect(content.knowledgePoints.length).toBeGreaterThan(0);
    expect(content.outline).toHaveLength(3);
  });

  it('fetchKnowledge 返回知识点与关系', async () => {
    const data = await api.fetchKnowledge('calc7');
    expect(data.concepts.some((concept) => concept.title === '先抓住「变化率」')).toBe(true);
    expect(data.relations.length).toBe(data.concepts.length - 1);
    expect(data.stats.conceptCount).toBe(data.concepts.length);
  });

  it('markChapterProgress 会让演示知识点进入学习中', async () => {
    await api.markChapterProgress({ bookId: 'calc7', chapterId: 'ch2', status: 'learning', mastery: 42 });
    const data = await api.fetchKnowledge('calc7');
    expect(data.concepts.find((concept) => concept.chapterId === 'ch2').status).toBe('learning');
  });

  it('fetchBooks 会反映演示模式中的章节学习进度', async () => {
    await api.markChapterProgress({ bookId: 'calc7', chapterId: 'ch2', status: 'learning', mastery: 42 });
    const book = await api.fetchBook('calc7');
    expect(book.chapters.find((chapter) => chapter.id === 'ch2')).toMatchObject({
      status: 'learning',
      progressPct: 42,
    });
  });

  it('未准备的章节返回 null', async () => {
    expect(await api.fetchStudyContent('calc7', 'ch1')).toBeNull();
  });

  it('ask 返回回答与教材锚点', async () => {
    const res = await api.ask({ question: '为什么一定要取极限？', bookId: 'calc7', chapterId: 'ch2' });
    expect(res.text).toBeTruthy();
    expect(res.sources.length).toBeGreaterThan(0);
  });
});
