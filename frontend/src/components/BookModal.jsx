import { useRef, useState } from 'react';
import { useBooks } from '../state/BookContext.jsx';
import { useToast } from '../state/ToastContext.jsx';
import { api } from '../services/api.js';

/** 更换教材弹窗：可切换已有教材，也可上传文本型 PDF。 */
export default function BookModal({ open, onClose }) {
  const { books, currentBookId, setCurrentBookId, refreshBooks } = useBooks();
  const toast = useToast();
  const inputRef = useRef(null);
  const [uploading, setUploading] = useState(false);

  if (!open) return null;

  const choose = (book) => {
    if (book.id !== currentBookId) {
      setCurrentBookId(book.id);
      const name = [book.title, book.edition].filter(Boolean).join(' ');
      toast(`已切换为《${name}》`);
    }
    onClose();
  };

  const upload = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      toast('目前只支持上传 PDF 文件');
      return;
    }
    setUploading(true);
    try {
      const uploaded = await api.uploadBook(file);
      const list = await refreshBooks();
      const imported = list.find((book) => book.id === uploaded.id) ?? uploaded;
      setCurrentBookId(imported.id);
      toast(`《${imported.title}》已上传并识别 ${imported.chapters.length} 个章节`);
      onClose();
    } catch (error) {
      toast(error.message || 'PDF 上传失败');
    } finally {
      setUploading(false);
    }
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
          <input
            ref={inputRef}
            className="upload-input"
            type="file"
            accept=".pdf,application/pdf"
            onChange={upload}
            aria-label="选择 PDF 教材"
          />
          <button className="upload" type="button" onClick={() => inputRef.current?.click()} disabled={uploading}>
            {uploading ? '正在上传并识别目录…' : '＋ 上传新教材（PDF）'}
          </button>
        </div>
      </div>
    </div>
  );
}
