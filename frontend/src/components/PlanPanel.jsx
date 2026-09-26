import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import ChapterList from './ChapterList.jsx';
import { api } from '../services/api.js';
import { useBooks } from '../state/BookContext.jsx';
import { useToast } from '../state/ToastContext.jsx';

/**
 * 主页右侧：学习计划面板（计划头 + 短期目标 + 启动按钮 + 章节目录）。
 *
 * 「调整计划」是真的会重算的：调后端 `POST /api/books/{id}/plan` 再重读列表。
 * 以前它只弹一句「已为你重新规划本周进度」，什么都没做——按钮说了它会做的事，
 * 就必须真的做，否则用户会对着一个没变化的计划以为功能坏了（或以为 AI 没用）。
 */
export default function PlanPanel({ book }) {
  const navigate = useNavigate();
  const toast = useToast();
  const { refreshBooks } = useBooks();
  const [replanning, setReplanning] = useState(false);
  const { plan } = book;

  const todayChapter = book.chapters.find((c) => c.isToday) ?? book.chapters[0];
  const startStudy = () => navigate(`/study/${book.id}/${todayChapter.id}`);

  const adjustPlan = async () => {
    if (replanning) return;
    setReplanning(true);
    try {
      await api.regeneratePlan(book.id);
      // 展示用的 plan 是后端序列化后的形态，必须重读列表才拿得到
      await refreshBooks();
      toast('已重新规划本周进度');
    } catch (error) {
      toast(error.message || '重新规划失败，请稍后重试');
    } finally {
      setReplanning(false);
    }
  };

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
      <div className="plan-body">
        <div className="goal-card">
          <div className="goal-label">{plan.goalLabel}</div>
          <strong>{plan.goal}</strong>
          <p>{plan.remaining}</p>
        </div>
        <button className="start-btn" onClick={startStudy}>
          开启今日学习
        </button>
      </div>
      <div className="chapter-dock">
        <ChapterList book={book} onAdjust={adjustPlan} adjusting={replanning} />
      </div>
    </div>
  );
}
