import { studyContents } from '../data/books.js';

/**
 * 演示模式的掌握度计算：与后端 `app/services/progress.py` 同一套公式，
 * 保证「无后端演示」和「接后端」两条路径算出来的数一样。
 *
 *     覆盖度     = 读过的段落数 / 本章可读段落数            权重 50
 *     互动度     = min(不同提问数, 5) / 5                   权重 25
 *     自测正确率 = 答对题数 / 答题总数（无记录时该项缺失）    权重 25
 *
 * 无自测记录时，自测权重按比例并入前两项；覆盖度只认本章真实锚点，
 * 提问去重并封顶（防刷分）。返回结构与后端 `/events` 接口一致。
 */
export const COVERAGE_WEIGHT = 50;
export const ENGAGEMENT_WEIGHT = 25;
export const QUIZ_WEIGHT = 25;
export const MAX_COUNTED_QUESTIONS = 5;
export const LEARNED_THRESHOLD = 80;

const EVENTS_KEY = 'ai_reader.learningEvents';

/** 本章可读段落（带锚点的正文段落）的 id 列表。 */
export function chapterParagraphIds(bookId, chapterId) {
  const paragraphs = studyContents[bookId]?.[chapterId]?.paragraphs ?? [];
  return paragraphs.flatMap((para) =>
    (para.segs ?? []).filter((seg) => seg.t === 'src' && seg.id).map((seg) => seg.id),
  );
}

function readAll() {
  try {
    return JSON.parse(localStorage.getItem(EVENTS_KEY) || '{}');
  } catch {
    return {};
  }
}

/** 读取某章的原始事件列表。 */
export function readEvents(bookId, chapterId) {
  return readAll()[bookId]?.[chapterId] ?? [];
}

function appendEvents(bookId, chapterId, events) {
  if (!events.length) return;
  const store = readAll();
  store[bookId] ??= {};
  store[bookId][chapterId] = [...(store[bookId][chapterId] ?? []), ...events];
  localStorage.setItem(EVENTS_KEY, JSON.stringify(store));
}

/** 按事件算出掌握度与状态（纯函数，便于测试）。 */
export function computeProgress(bookId, chapterId, events = readEvents(bookId, chapterId)) {
  const validIds = chapterParagraphIds(bookId, chapterId);
  const validSet = new Set(validIds);

  const readAnchors = new Set(
    events.filter((event) => event.kind === 'read' && validSet.has(event.anchorId)).map((event) => event.anchorId),
  );
  const questions = new Set(
    events.filter((event) => event.kind === 'ask' && event.detail).map((event) => event.detail),
  );
  const answers = events.filter((event) => event.kind === 'quiz').map((event) => Number(event.value) || 0);
  const completed = events.some((event) => event.kind === 'complete');

  const coverage = validIds.length ? readAnchors.size / validIds.length : 0;
  const engagement = Math.min(questions.size, MAX_COUNTED_QUESTIONS) / MAX_COUNTED_QUESTIONS;
  const accuracy = answers.length ? answers.reduce((sum, value) => sum + value, 0) / answers.length : null;

  let coverageWeight;
  let engagementWeight;
  let quizWeight;
  let note;
  if (accuracy === null) {
    const kept = COVERAGE_WEIGHT + ENGAGEMENT_WEIGHT;
    coverageWeight = (COVERAGE_WEIGHT / kept) * 100;
    engagementWeight = (ENGAGEMENT_WEIGHT / kept) * 100;
    quizWeight = 0;
    note = '暂无自测记录，自测权重已按比例并入前两项';
  } else {
    coverageWeight = COVERAGE_WEIGHT;
    engagementWeight = ENGAGEMENT_WEIGHT;
    quizWeight = QUIZ_WEIGHT;
    note = '已计入自测正确率';
  }

  const parts = [
    ['coverage', '已读段落', coverage, coverageWeight],
    ['engagement', '提问互动', engagement, engagementWeight],
    ['quiz', '自测正确率', accuracy ?? 0, quizWeight],
  ];
  const breakdown = parts.map(([key, label, value, weight]) => ({
    key,
    label,
    value: key === 'quiz' && accuracy === null ? null : Math.round(value * 1000) / 1000,
    weight: Math.round(weight * 10) / 10,
    score: Math.round(value * weight * 10) / 10,
  }));
  const computed = Math.round(breakdown.reduce((sum, item) => sum + item.score, 0));
  const status = completed || computed >= LEARNED_THRESHOLD ? 'learned' : events.length ? 'learning' : 'planned';

  return {
    bookId,
    chapterId,
    status,
    computed,
    mastery: computed,
    breakdown,
    note,
    signals: {
      paragraphsRead: readAnchors.size,
      paragraphsTotal: validIds.length,
      askCount: questions.size,
      quizCount: answers.length,
      quizAccuracy: accuracy === null ? null : Math.round(accuracy * 1000) / 1000,
      completed,
    },
  };
}

/** 记录一次本地事件并返回重算结果（演示模式用）。 */
export function recordLocalEvent(bookId, chapterId, { kind, anchorIds = [], question = '', correct } = {}) {
  const pending = [];

  if (kind === 'read') {
    const valid = new Set(chapterParagraphIds(bookId, chapterId));
    const already = new Set(readEvents(bookId, chapterId).filter((e) => e.kind === 'read').map((e) => e.anchorId));
    for (const anchorId of new Set(anchorIds)) {
      if (valid.has(anchorId) && !already.has(anchorId)) {
        pending.push({ kind: 'read', anchorId });
      }
    }
  } else if (kind === 'ask') {
    if ((question || '').trim()) pending.push({ kind: 'ask', detail: question.trim().slice(0, 200) });
  } else if (kind === 'quiz') {
    pending.push({ kind: 'quiz', value: correct ? 1 : 0 });
  } else if (kind === 'open' || kind === 'complete') {
    pending.push({ kind });
  }

  appendEvents(bookId, chapterId, pending);
  return computeProgress(bookId, chapterId);
}
