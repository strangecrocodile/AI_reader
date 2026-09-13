import { books, studyContents } from './books.js';

/**
 * 演示模式的语义关系标注：知识点 id → 它依赖的前置概念名。
 *
 * 真实数据由后端知识抽取生成（见 backend/app/services/concepts.py）；
 * 这里手工标注，保证「无模型、无后端」时演示模式与后端模式看到同一套字段。
 * 其中「极限」在演示数据里没有对应的知识点卡片，用于演示「教材外前置」。
 */
const DEMO_PREREQUISITES = {
  'kp-rate': ['极限'],
  'kp-limit': ['先抓住「变化率」'],
};

/** 演示模式使用的知识点图谱数据（结构与后端 /api/books/{id}/knowledge 一致）。 */
export function knowledgeFor(bookId, progressByChapter = {}) {
  const book = books.find((item) => item.id === bookId);
  const concepts = [];
  const byTitle = new Map();

  for (const chapter of book?.chapters ?? []) {
    const content = studyContents[bookId]?.[chapter.id];
    for (const point of content?.knowledgePoints ?? []) {
      const summary = point.body.map((part) => part.v).join('');
      const sourceId = point.sourceId ?? null;
      const concept = {
        id: `${chapter.id}:${point.id}`,
        title: point.title,
        label: point.title,
        definition: summary,
        summary,
        chapterId: chapter.id,
        chapterTitle: content.heading,
        chapters: [chapter.id],
        sourceId,
        sourceLabel: point.sourceLabel ?? '定位教材：原文',
        anchors: sourceId ? [sourceId] : [],
        anchorCount: sourceId ? 1 : 0,
        prerequisites: [...(DEMO_PREREQUISITES[point.id] ?? [])],
        method: 'demo',
        status: progressByChapter[chapter.id]?.status ?? 'planned',
        mastery: progressByChapter[chapter.id]?.mastery ?? 0,
      };
      concepts.push(concept);
      byTitle.set(concept.title, concept);
    }
  }

  const relations = [];
  const linked = new Set();
  const external = new Map();

  for (const concept of concepts) {
    for (const name of concept.prerequisites) {
      const target = byTitle.get(name);
      if (target) {
        linked.add(`${concept.id}->${target.id}`);
        relations.push({
          id: `${concept.id}->${target.id}`,
          source: concept.id,
          target: target.id,
          type: 'prerequisite',
          label: '前置',
        });
        continue;
      }
      if (!external.has(name)) external.set(name, new Set());
      external.get(name).add(concept.title);
    }
  }

  // 学习顺序兜底边：同章节相邻知识点，若已有前置边则不再重复连接
  for (let i = 1; i < concepts.length; i += 1) {
    const previous = concepts[i - 1];
    const current = concepts[i];
    if (linked.has(`${previous.id}->${current.id}`) || linked.has(`${current.id}->${previous.id}`)) {
      continue;
    }
    linked.add(`${previous.id}->${current.id}`);
    relations.push({
      id: `${previous.id}->${current.id}`,
      source: previous.id,
      target: current.id,
      type: 'sequence',
      label: '学习顺序',
    });
  }

  const unresolved = [...external.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([name, requiredBy]) => ({ name, requiredBy: [...requiredBy] }));

  return {
    bookId,
    bookTitle: book?.title ?? '',
    concepts,
    relations,
    unresolved,
    methods: ['demo'],
    stats: {
      conceptCount: concepts.length,
      learnedCount: concepts.filter((concept) => concept.status !== 'planned').length,
      relationCount: relations.length,
      prerequisiteCount: relations.filter((relation) => relation.type === 'prerequisite').length,
      unresolvedCount: unresolved.length,
    },
  };
}
