import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { api, configureApiBase } from '../services/api.js';

/**
 * 演示模式的自测闭环。
 *
 * 这条链路单独测，因为它**没有后端**：题目与答案都来自前端演示数据
 * （`data/books.js` 的 `quiz`）。演示模式恰恰是最需要它的地方——评委多半不会先配
 * `.env`，如果这里出不了题，掌握度里那 25% 就永远显示「未计入」，
 * 而这个闭环正是最该被看到的东西。
 */
beforeEach(() => {
  configureApiBase(''); // 演示模式
  localStorage.clear();
});

afterEach(() => {
  configureApiBase('');
});

describe('演示模式自测', () => {
  it('演示章节能出题，且不下发答案', async () => {
    const quiz = await api.fetchQuiz('calc7', 'ch2');

    expect(quiz.total).toBeGreaterThanOrEqual(3);
    for (const question of quiz.questions) {
      expect(question.options.length).toBeGreaterThanOrEqual(2);
      expect(question).not.toHaveProperty('answerIndex');
      expect(question).not.toHaveProperty('answer');
    }
  });

  it('没有演示数据的问题章节不出题，而不是报错', async () => {
    const quiz = await api.fetchQuiz('calc7', 'ch9');

    expect(quiz.total).toBe(0);
    expect(quiz.questions).toEqual([]);
  });

  it('答对与答错都判得对，并把正确答案带回来', async () => {
    const quiz = await api.fetchQuiz('calc7', 'ch2');
    const first = quiz.questions[0];

    const right = await api.answerQuiz('calc7', 'ch2', first.id, 0);
    expect(right.correct).toBe(true);
    expect(right.answer).toBe('平均变化率');

    const wrong = await api.answerQuiz('calc7', 'ch2', first.id, 1);
    expect(wrong.correct).toBe(false);
    expect(wrong.answer).toBe('平均变化率');
  });

  it('作答会真的推动掌握度里的自测项——这是这个闭环的意义', async () => {
    const quiz = await api.fetchQuiz('calc7', 'ch2');

    const result = await api.answerQuiz('calc7', 'ch2', quiz.questions[0].id, 0);

    const quizPart = result.progress.breakdown.find((item) => item.key === 'quiz');
    expect(quizPart.weight).toBe(25);
    expect(quizPart.value).toBe(1); // 答对 → 该项满分
    expect(result.progress.signals.quizCount).toBe(1);
  });

  it('题号不存在时报错，而不是静默给一个「对了」', async () => {
    await expect(api.answerQuiz('calc7', 'ch2', '不存在', 0)).rejects.toThrow('这道题不存在');
  });
});
