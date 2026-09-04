import { useNavigate } from 'react-router-dom';
import ChapterList from './ChapterList.jsx';
import { useToast } from '../state/ToastContext.jsx';

/** 主页右侧：学习计划面板（计划头 + 短期目标 + 启动按钮 + 章节目录）。 */
export default function PlanPanel({ book }) {
  const navigate = useNavigate();
  const toast = useToast();
  const { plan } = book;

  const todayChapter = book.chapters.find((c) => c.isToday) ?? book.chapters[0];
  const startStudy = () => navigate(`/study/${book.id}/${todayChapter.id}`);

  return (
    <div className="plan-panel">
      <div className="plan-head">
        <div>
          <div className="eyebrow">{plan.eyebrow || '本周学习计划'}</div>
          <h1>
            {plan.headline.map((line) => (
              <div key={line}>{line}</div>
            ))}
          </h1>
          <p className="sub">{plan.sub}</p>
        </div>
        <span className="book-tag">{book.tag}</span>
      </div>
      <div className="goal-card">
        <div className="goal-label">{plan.goalLabel}</div>
        <strong>{plan.goal}</strong>
        <p>{plan.remaining}</p>
      </div>
      <button className="start-btn" onClick={startStudy}>
        开启今日学习　→
      </button>
      <ChapterList book={book} onAdjust={() => toast('已为你重新规划本周进度')} />
    </div>
  );
}
