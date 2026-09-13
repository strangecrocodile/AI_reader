import { beforeEach, describe, expect, it } from 'vitest';
import {
  chapterParagraphIds,
  computeProgress,
  readEvents,
  recordLocalEvent,
} from '../services/progress.js';

const BOOK = 'calc7';
const CHAPTER = 'ch2';
const ANCHORS = chapterParagraphIds(BOOK, CHAPTER);

function read(anchorIds) {
  return recordLocalEvent(BOOK, CHAPTER, { kind: 'read', anchorIds });
}

function ask(question) {
  return recordLocalEvent(BOOK, CHAPTER, { kind: 'ask', question });
}

beforeEach(() => {
  localStorage.clear();
});

describe('演示模式掌握度（与后端 services/progress.py 同一公式）', () => {
  it('章节可读段落就是演示数据里的原文锚点', () => {
    expect(ANCHORS).toEqual(['source-rate', 'source-limit', 'source-tangent']);
  });

  it('没有事件时是待学习，掌握度 0', () => {
    const result = computeProgress(BOOK, CHAPTER);

    expect(result.status).toBe('planned');
    expect(result.mastery).toBe(0);
    expect(result.signals.paragraphsTotal).toBe(3);
  });

  it('只进入章节不产生掌握度', () => {
    const result = recordLocalEvent(BOOK, CHAPTER, { kind: 'open' });

    expect(result.status).toBe('learning');
    expect(result.mastery).toBe(0);
  });

  it('读完全部段落拿到覆盖度权重（无自测时按 66.7 计）', () => {
    const result = read(ANCHORS);

    expect(result.signals.paragraphsRead).toBe(3);
    expect(result.breakdown.map((item) => [item.key, item.weight])).toEqual([
      ['coverage', 66.7],
      ['engagement', 33.3],
      ['quiz', 0],
    ]);
    expect(result.computed).toBe(67);
    expect(result.status).toBe('learning');
  });

  it('读完并提问两次达到已掌握阈值', () => {
    read(ANCHORS);
    ask('为什么一定要取极限？');
    const result = ask('平均变化率和导数是什么关系？');

    expect(result.signals.askCount).toBe(2);
    expect(result.computed).toBe(80);
    expect(result.status).toBe('learned');
  });

  it('非法锚点与重复上报都不计分', () => {
    read(['不存在的锚点']);
    expect(computeProgress(BOOK, CHAPTER).signals.paragraphsRead).toBe(0);

    read(ANCHORS.slice(0, 2));
    const result = read(ANCHORS.slice(0, 2));
    expect(result.signals.paragraphsRead).toBe(2);
    expect(readEvents(BOOK, CHAPTER).filter((event) => event.kind === 'read')).toHaveLength(2);
  });

  it('有自测记录时三项权重完整计入', () => {
    read(ANCHORS);
    ask('问题一');
    const result = recordLocalEvent(BOOK, CHAPTER, { kind: 'quiz', correct: true });

    expect(result.breakdown.map((item) => item.weight)).toEqual([50, 25, 25]);
    expect(result.computed).toBe(80);
    expect(result.note).toBe('已计入自测正确率');
  });

  it('标记学完直接置为已掌握，事件按章节分开存储', () => {
    const result = recordLocalEvent(BOOK, CHAPTER, { kind: 'complete' });

    expect(result.status).toBe('learned');
    expect(result.signals.completed).toBe(true);
    expect(readEvents(BOOK, 'ch1')).toEqual([]);
    expect(readEvents(BOOK, CHAPTER)).toHaveLength(1);
  });
});
