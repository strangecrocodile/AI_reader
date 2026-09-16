import { useNavigate } from 'react-router-dom';

/** 后端返回 learned，演示数据用 done，两种都算「已完成」。 */
const DONE_STATUSES = ['done', 'learned'];

/** 章节目录：点击章节进入对应学习页。 */
export default function ChapterList({ book, onAdjust }) {
  const navigate = useNavigate();
  const goChapter = (chapterId) => navigate(`/study/${book.id}/${chapterId}`);

  return (
    <>
      <div className="section-title">
        <h3>学习轨道</h3>
        <button onClick={onAdjust}>调整计划</button>
      </div>
      {book.chapters.map((chapter) => (
        <button key={chapter.id} className="chapter" onClick={() => goChapter(chapter.id)}>
          <span className="chapter-num">{chapter.num}</span>
          <span className="chapter-main">
            <strong>{chapter.title}</strong>
            <small> {chapter.meta}</small>
            <span className="progress">
              <i style={{ width: `${chapter.progressPct}%` }}></i>
            </span>
          </span>
          <span className={chapter.isToday ? 'today' : 'chapter-state'}>
            {DONE_STATUSES.includes(chapter.status) ? '✓' : chapter.isToday ? '今日' : '→'}
          </span>
        </button>
      ))}
    </>
  );
}
