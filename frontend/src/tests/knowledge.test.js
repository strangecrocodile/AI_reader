import { describe, expect, it } from 'vitest';
import { knowledgeFor } from '../data/knowledge.js';

/**
 * 演示模式的知识点图谱必须与后端 /api/books/{id}/knowledge 同结构，
 * 否则「无后端演示」与「接后端」两条路径会长歪。
 */
describe('演示模式知识点图谱数据', () => {
  it('概念、关系与统计自洽，且关系两端都指向存在的节点', () => {
    const data = knowledgeFor('calc7');
    const ids = new Set(data.concepts.map((concept) => concept.id));

    expect(data.concepts.length).toBeGreaterThan(0);
    expect(ids.size).toBe(data.concepts.length);
    for (const relation of data.relations) {
      expect(ids.has(relation.source)).toBe(true);
      expect(ids.has(relation.target)).toBe(true);
      expect(relation.source).not.toBe(relation.target);
      expect(['prerequisite', 'sequence']).toContain(relation.type);
      expect(relation.label).toBeTruthy();
    }

    expect(data.stats.conceptCount).toBe(data.concepts.length);
    expect(data.stats.relationCount).toBe(data.relations.length);
    expect(data.stats.prerequisiteCount).toBe(
      data.relations.filter((relation) => relation.type === 'prerequisite').length,
    );
    expect(data.stats.unresolvedCount).toBe(data.unresolved.length);
  });

  it('每个概念都带可回链原文的字段', () => {
    const data = knowledgeFor('calc7');

    for (const concept of data.concepts) {
      expect(concept.title).toBeTruthy();
      expect(concept.definition).toBeTruthy();
      expect(concept.chapterId).toBeTruthy();
      expect(concept.chapterTitle).toBeTruthy();
      expect(concept.chapters).toContain(concept.chapterId);
      expect(concept.anchorCount).toBe(concept.anchors.length);
      expect(Array.isArray(concept.prerequisites)).toBe(true);
    }
  });

  it('有卡片的前置连成前置边，没有卡片的归入教材外前置', () => {
    const data = knowledgeFor('calc7');

    expect(data.relations.some((relation) => relation.type === 'prerequisite')).toBe(true);
    expect(data.relations.some((relation) => relation.type === 'sequence')).toBe(true);
    expect(data.unresolved).toEqual([{ name: '极限', requiredBy: ['先抓住「变化率」'] }]);
  });

  it('学习进度回写到知识点状态与掌握度', () => {
    const data = knowledgeFor('calc7', { ch2: { status: 'learning', mastery: 42 } });

    expect(data.concepts.every((concept) => concept.status === 'learning')).toBe(true);
    expect(data.concepts.every((concept) => concept.mastery === 42)).toBe(true);
    expect(data.stats.learnedCount).toBe(data.concepts.length);
  });

  it('未知教材返回空图谱而不是抛错', () => {
    const data = knowledgeFor('unknown-book');

    expect(data.concepts).toEqual([]);
    expect(data.relations).toEqual([]);
    expect(data.unresolved).toEqual([]);
    expect(data.stats.conceptCount).toBe(0);
  });
});
