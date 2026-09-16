import { useState } from 'react';
import BookCard from '../components/BookCard.jsx';
import PlanPanel from '../components/PlanPanel.jsx';
import BookModal from '../components/BookModal.jsx';
import SpatialBackdrop from '../components/SpatialBackdrop.jsx';
import StateCard from '../components/StateCard.jsx';
import { useBooks } from '../state/BookContext.jsx';

/** 主页：教材选择 + 学习计划 + 章节目录；教材为空或后端不可用时给出引导。 */
export default function HomePage() {
  const { books, loading, error, reload, currentBookId } = useBooks();
  const [modalOpen, setModalOpen] = useState(false);

  if (loading) {
    return (
      <section className="page active" aria-busy="true">
        <p className="loading-note">正在加载教材…</p>
      </section>
    );
  }

  if (error) {
    return (
      <section className="page active">
        <StateCard
          title="连不上教材服务"
          description="后端接口没有响应。请确认后端已启动（默认 http://localhost:8000），并检查 frontend/.env 里的 VITE_API_BASE_URL。"
          hint={`错误信息：${error.message || error}`}
          actionLabel="重试"
          onAction={reload}
        />
      </section>
    );
  }

  if (!books || books.length === 0) {
    return (
      <section className="page active">
        <StateCard
          title="还没有教材"
          description="上传一份 PDF / Word(.docx) / 纯文本(.txt/.md) 教材即可开始学习。"
          hint="没有现成教材？在 backend 目录执行 scripts/make_demo_pdf.py 可生成一份团队原创的示例教材。"
          actionLabel="上传教材"
          onAction={() => setModalOpen(true)}
        />
        <BookModal open={modalOpen} onClose={() => setModalOpen(false)} />
      </section>
    );
  }

  const book = books.find((b) => b.id === currentBookId) ?? books[0];
  const todayChapter = book.chapters.find((chapter) => chapter.isToday) ?? book.chapters[0];

  return (
    <section className="page active home-page">
      <SpatialBackdrop />
      <div className="home-shell" data-testid="home-shell">
        <aside className="home-command" aria-label="学习概览">
          <div className="command-card command-card-primary">
            <span className="eyebrow">AI Reader</span>
            <h2>把教材压成今天能完成的学习轨道。</h2>
            <p className="sub">{book.plan.sub}</p>
          </div>
          <div className="command-stack">
            <div className="metric-tile">
              <span>当前进度</span>
              <strong>{book.progressText}</strong>
            </div>
            <div className="metric-tile">
              <span>今日焦点</span>
              <strong>
                {todayChapter ? `${todayChapter.num} · ${todayChapter.title}` : '等待计划生成'}
              </strong>
            </div>
          </div>
        </aside>
        <BookCard book={book} onSwap={() => setModalOpen(true)} />
        <PlanPanel book={book} />
      </div>
      <BookModal open={modalOpen} onClose={() => setModalOpen(false)} />
    </section>
  );
}
