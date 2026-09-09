import { books, studyContents } from './books.js';

/** 演示模式使用的知识点聚合数据。 */
export function knowledgeFor(bookId, progressByChapter = {}) {
  const book = books.find((item) => item.id === bookId);
  const concepts = [];

  for (const chapter of book?.chapters ?? []) {
    const content = studyContents[bookId]?.[chapter.id];
    for (const point of content?.knowledgePoints ?? []) {
      concepts.push({
        id: `${chapter.id}:${point.id}`,
        title: point.title,
        summary: point.body.map((part) => part.v).join(''),
        chapterId: chapter.id,
        chapterTitle: content.heading,
        sourceId: point.sourceId ?? null,
        sourceLabel: point.sourceLabel ?? '定位教材：原文',
        status: progressByChapter[chapter.id]?.status ?? 'planned',
        mastery: progressByChapter[chapter.id]?.mastery ?? 0,
      });
    }
  }

  return {
    bookId,
    bookTitle: book?.title ?? '',
    concepts,
    relations: concepts.slice(1).map((concept, index) => ({
      id: `${concepts[index].id}->${concept.id}`,
      source: concepts[index].id,
      target: concept.id,
      type: 'sequence',
      label: '学习顺序',
    })),
    stats: {
      conceptCount: concepts.length,
      learnedCount: concepts.filter((concept) => concept.status !== 'planned').length,
      relationCount: Math.max(0, concepts.length - 1),
    },
  };
}
