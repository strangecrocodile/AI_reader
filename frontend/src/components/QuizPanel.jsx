import { useState } from 'react';

/**
 * 章末自测：让掌握度里那 25% 的「自测正确率」有东西可算。
 *
 * 这个闭环此前是断的——公式里自测占 25 分，界面上却永远显示「未计入」。断点不在
 * 公式，在于**根本没有出题的地方**。所以这里最重要的不是题目多漂亮，而是答完之后
 * 掌握度面板会真的变：`onAnswer` 把后端重算好的拆分说明交回去。
 *
 * 答案只在后端（判卷走 `onAnswer`），前端拿不到——掌握度才不是「前端自己说对了」。
 * 材料不足时后端给 0 道题，这里如实说明，不硬凑。
 */

/** 选项字母，让选项看起来像题而不是像列表。 */
const OPTION_LABELS = ['A', 'B', 'C', 'D', 'E', 'F'];

export default function QuizPanel({ quiz, onAnswer }) {
  const [answers, setAnswers] = useState({});
  const [pending, setPending] = useState('');

  if (!quiz) return null;

  const questions = quiz.questions ?? [];
  if (questions.length === 0) {
    return (
      <div className="quiz-panel" data-testid="quiz-panel">
        <div className="thread-list-head">
          <span>本章自测</span>
        </div>
        <p className="quiz-note" data-testid="quiz-empty">
          这一章暂时出不了题——自测题从章节里抽出的知识点生成，这一章还没抽出可考的概念。
        </p>
      </div>
    );
  }

  const answered = Object.keys(answers).length;
  const correct = Object.values(answers).filter((item) => item.correct).length;

  const choose = async (question, index) => {
    if (answers[question.id] || pending) return; // 一题只判一次，判完就锁定
    setPending(question.id);
    const result = await onAnswer?.(question.id, index);
    setPending('');
    // 判卷结果里没有「用户选了什么」，得自己记下来——否则选错的那一项标不出来
    if (result) setAnswers((prev) => ({ ...prev, [question.id]: { ...result, choice: index } }));
  };

  return (
    <div className="quiz-panel" data-testid="quiz-panel">
      <div className="thread-list-head">
        <span>本章自测</span>
        <span data-testid="quiz-score">
          {answered > 0 ? `已答 ${answered} / ${questions.length} · 对 ${correct}` : `${questions.length} 题`}
        </span>
      </div>
      <ul className="quiz-list">
        {questions.map((question) => {
          const result = answers[question.id];
          return (
            <li key={question.id} className="quiz-item" data-testid={`quiz-${question.id}`}>
              <p className="quiz-prompt">{question.prompt}</p>
              <div className="quiz-options">
                {question.options.map((option, index) => {
                  const picked = result && result.choice === index;
                  const state = !result
                    ? ''
                    : index === result.answerIndex
                      ? ' correct'
                      : picked
                        ? ' wrong'
                        : '';
                  return (
                    <button
                      key={option}
                      type="button"
                      className={`quiz-option${state}`}
                      data-testid={`quiz-option-${question.id}-${index}`}
                      onClick={() => choose(question, index)}
                      disabled={Boolean(result) || pending === question.id}
                    >
                      <b>{OPTION_LABELS[index] ?? index + 1}</b>
                      {option}
                    </button>
                  );
                })}
              </div>
              {result && (
                <p
                  className={`quiz-verdict ${result.correct ? 'ok' : 'no'}`}
                  data-testid={`quiz-verdict-${question.id}`}
                >
                  {result.correct ? '答对了' : `答错了，正确答案是「${result.answer}」`}
                </p>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
