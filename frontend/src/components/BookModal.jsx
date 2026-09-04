import { useBooks } from '../state/BookContext.jsx';
import { useToast } from '../state/ToastContext.jsx';

/** 更换教材弹窗：可切换到其他教材；「上传新教材」为演示占位。 */
export default function BookModal({ open, onClose }) {
  const { books, currentBookId, setCurrentBookId } = useBooks();
  const toast = useToast();

  if (!open) return null;

  const choose = (book) => {
    if (book.id !== currentBookId) {
      setCurrentBookId(book.id);
      const name = [book.title, book.edition].filter(Boolean).join(' ');
      toast(`已切换为《${name}》`);
    }
    onClose();
  };

  return (
    <div className="modal open" role="dialog" aria-modal="true" aria-label="选择学习材料" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose} aria-label="关闭">
          ×
        </button>
        <div className="eyebrow">选择学习材料</div>
        <h2 style={{ marginTop: 7 }}>更换教材</h2>
        <div className="book-choices">
          {books.map((book) => (
            <button key={book.id} className="book-choice" onClick={() => choose(book)}>
              <span>
                <b>
                  {book.title} · {book.edition || '第 3 版'}
                </b>
                <br />
                <small>
                  {book.author} · {book.chapters.length} 个已识别章节
                </small>
              </span>
              <span>{book.id === currentBookId ? '当前' : '→'}</span>
            </button>
          ))}
          <div className="upload" onClick={() => toast('演示模式：已模拟上传并识别目录')} role="button" tabIndex={0}>
            ＋ 上传新教材（PDF / EPUB）
          </div>
        </div>
      </div>
    </div>
  );
}
