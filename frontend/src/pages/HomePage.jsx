import { useState } from 'react';
import BookCard from '../components/BookCard.jsx';
import PlanPanel from '../components/PlanPanel.jsx';
import BookModal from '../components/BookModal.jsx';
import { useBooks } from '../state/BookContext.jsx';

/** 主页：教材选择 + 学习计划 + 章节目录。 */
export default function HomePage() {
  const { books, loading, currentBookId } = useBooks();
  const [modalOpen, setModalOpen] = useState(false);

  if (loading || !books) {
    return (
      <section className="page active" aria-busy="true">
        <p className="loading-note">正在加载教材…</p>
      </section>
    );
  }

  const book = books.find((b) => b.id === currentBookId) ?? books[0];

  return (
    <section className="page active">
      <div className="home-grid">
        <BookCard book={book} onSwap={() => setModalOpen(true)} />
        <PlanPanel book={book} />
      </div>
      <BookModal open={modalOpen} onClose={() => setModalOpen(false)} />
    </section>
  );
}
