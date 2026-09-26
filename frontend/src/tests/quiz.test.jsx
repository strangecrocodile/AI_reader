import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import App from '../App.jsx';
import { api } from '../services/api.js';
import { BookProvider } from '../state/BookContext.jsx';
import { ToastProvider } from '../state/ToastContext.jsx';

/**
 * 章末自测。
 *
 * 这里要守住的核心只有一条：**答完题，掌握度面板真的变**。
 *
 * 掌握度公式里自测占 25 分，界面上却一直显示「未计入」——断点不在公式，在于
 * 根本没有出题的地方。所以「面板更新了」这个断言比题目长得漂不漂亮重要得多。
 * 另外，答案只在后端，前端拿不到，掌握度才不是「前端自己说对了」。
 */

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

function renderApp() {
  return render(
    <MemoryRouter initialEntries={['/study/calc7/ch2']}>
      <BookProvider>
        <ToastProvider>
          <App />
        </ToastProvider>
      </BookProvider>
    </MemoryRouter>,
  );
}

const QUIZ = {
  chapterId: 'ch2',
  total: 1,
  model: 'mock',
  questions: [
    {
      id: 'ch2-q1',
      kind: 'cloze',
      prompt: '比值 Δy / Δx 衡量区间内的平均快慢，称为 ____。',
      options: ['平均变化率', '瞬时变化率', '导数', '极限'],
    },
  ],
};

/** 后端判卷后的返回：正确答案是下标 0。 */
function graded({ correct }) {
  return {
    correct,
    answerIndex: 0,
    answer: '平均变化率',
    anchorId: 'source-rate',
    progress: {
      status: 'learning',
      mastery: correct ? 58 : 33,
      computed: correct ? 58 : 33,
      breakdown: [
        { key: 'coverage', label: '已读段落', value: 0.5, weight: 50, score: 25 },
        { key: 'engagement', label: '提问互动', value: 0, weight: 25, score: 0 },
        { key: 'quiz', label: '自测正确率', value: correct ? 1 : 0, weight: 25, score: correct ? 25 : 0 },
      ],
      note: '已计入自测正确率',
      signals: {
        paragraphsRead: 3,
        paragraphsTotal: 6,
        askCount: 0,
        quizCount: 1,
        quizAccuracy: correct ? 1 : 0,
        completed: false,
      },
    },
  };
}

async function openQuiz(quiz = QUIZ) {
  vi.spyOn(api, 'fetchQuiz').mockResolvedValue(quiz);
  renderApp();
  return screen.findByTestId('quiz-panel');
}

describe('章末自测', () => {
  it('列出题干与选项', async () => {
    await openQuiz();

    expect(screen.getByTestId('quiz-ch2-q1')).toHaveTextContent('平均变化率');
    expect(screen.getByTestId('quiz-option-ch2-q1-0')).toBeInTheDocument();
    expect(screen.getByTestId('quiz-option-ch2-q1-3')).toBeInTheDocument();
  });

  it('答对后掌握度面板的自测项从「未计入」变成真实分数', async () => {
    const answerQuiz = vi.spyOn(api, 'answerQuiz').mockResolvedValue(graded({ correct: true }));
    const user = userEvent.setup();
    await openQuiz();

    await user.click(screen.getByTestId('quiz-option-ch2-q1-0'));

    await waitFor(() => expect(answerQuiz).toHaveBeenCalledWith('calc7', 'ch2', 'ch2-q1', 0));
    expect(await screen.findByTestId('quiz-verdict-ch2-q1')).toHaveTextContent('答对了');
    // 掌握度面板随之更新：自测这一项不再是「未计入」而是 25 / 25
    const panel = await screen.findByTestId('mastery-panel');
    expect(panel).toHaveTextContent('自测正确率');
    expect(panel).toHaveTextContent('25 / 25');
  });

  it('答错时告诉用户正确答案', async () => {
    vi.spyOn(api, 'answerQuiz').mockResolvedValue(graded({ correct: false }));
    const user = userEvent.setup();
    await openQuiz();

    await user.click(screen.getByTestId('quiz-option-ch2-q1-2'));

    expect(await screen.findByTestId('quiz-verdict-ch2-q1')).toHaveTextContent(
      '答错了，正确答案是「平均变化率」',
    );
  });

  it('判过卷的题再点也不重复提交', async () => {
    const answerQuiz = vi.spyOn(api, 'answerQuiz').mockResolvedValue(graded({ correct: true }));
    const user = userEvent.setup();
    await openQuiz();

    await user.click(screen.getByTestId('quiz-option-ch2-q1-0'));
    await screen.findByTestId('quiz-verdict-ch2-q1');
    await user.click(screen.getByTestId('quiz-option-ch2-q1-1'));

    expect(answerQuiz).toHaveBeenCalledTimes(1);
  });

  it('判卷后把正确项标出来，选错的那项也标出来', async () => {
    vi.spyOn(api, 'answerQuiz').mockResolvedValue(graded({ correct: false }));
    const user = userEvent.setup();
    await openQuiz();

    await user.click(screen.getByTestId('quiz-option-ch2-q1-2'));

    await screen.findByTestId('quiz-verdict-ch2-q1');
    expect(screen.getByTestId('quiz-option-ch2-q1-0').className).toContain('correct');
    expect(screen.getByTestId('quiz-option-ch2-q1-2').className).toContain('wrong');
  });

  it('提交失败时说清原因，并允许重答', async () => {
    vi.spyOn(api, 'answerQuiz').mockRejectedValue(new Error('这道题不存在（题面可能已经更新）'));
    const user = userEvent.setup();
    await openQuiz();

    await user.click(screen.getByTestId('quiz-option-ch2-q1-0'));

    expect(await screen.findByText('这道题不存在（题面可能已经更新）')).toBeInTheDocument();
    // 没判成卷就不该锁住选项，否则用户连重试的机会都没有
    expect(screen.getByTestId('quiz-option-ch2-q1-1')).toBeEnabled();
  });

  it('出不了题时如实说明，而不是留一块空白', async () => {
    await openQuiz({ chapterId: 'ch2', total: 0, model: 'mock', questions: [] });

    expect(screen.getByTestId('quiz-empty')).toBeInTheDocument();
  });
});
