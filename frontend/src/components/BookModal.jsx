import { useEffect, useRef, useState } from 'react';
import { useBooks } from '../state/BookContext.jsx';
import { useToast } from '../state/ToastContext.jsx';
import { api } from '../services/api.js';

/** 与后端 services/ingest.py 的 SUPPORTED_MESSAGE 保持一致，前端只做前置提示。 */
const SUPPORTED_EXTENSIONS = ['.pdf', '.docx', '.txt', '.md'];
const FORMAT_HINT = '目前支持 PDF / Word(.docx) / 纯文本(.txt/.md) 教材；.doc 请先另存为 .docx';
/** 后端装了 LibreOffice 时才知道能直接吃 .doc（见 /api/capabilities）。 */
const DOC_EXTENSION = '.doc';
const ACCEPT_BASE = '.pdf,.docx,.txt,.md,application/pdf,text/plain,text/markdown';
/** 解析受限时给的补救建议：症状在界面上，原因多半在文档本身。 */
const WARNING_TIP =
  '常见原因：正文写在表格里、文本框里，或整本是扫描图片。把内容改为普通段落（Word 用「标题 1/2」做章节），或另存为 .md / .txt 后重新上传，识别效果最好。';

/** 更换教材弹窗：可切换已有教材，也可上传 PDF / Word / 纯文本教材。 */
export default function BookModal({ open, onClose }) {
  const { books, currentBookId, setCurrentBookId, refreshBooks } = useBooks();
  const toast = useToast();
  const inputRef = useRef(null);
  const [uploading, setUploading] = useState(false);
  const [warning, setWarning] = useState(null);
  // null 表示「还不知道」：按默认（不支持 .doc）处理，探测回来再放开
  const [legacyDoc, setLegacyDoc] = useState(null);

  useEffect(() => {
    if (!open) return undefined;
    let cancelled = false;
    api.fetchCapabilities().then((data) => {
      if (!cancelled && data) setLegacyDoc(Boolean(data.legacyDoc));
    });
    return () => {
      cancelled = true;
    };
  }, [open]);

  if (!open) return null;

  const extensions = legacyDoc ? [...SUPPORTED_EXTENSIONS, DOC_EXTENSION] : SUPPORTED_EXTENSIONS;
  const formatHint = legacyDoc
    ? '目前支持 PDF / Word(.docx / .doc) / 纯文本(.txt/.md) 教材'
    : FORMAT_HINT;
  const accept = legacyDoc ? `${ACCEPT_BASE},.doc,application/msword` : ACCEPT_BASE;

  /** 关闭时清掉上一次的解析提示，免得再打开时挂着一条过期的警告。 */
  const close = () => {
    setWarning(null);
    onClose();
  };

  const choose = (book) => {
    if (book.id !== currentBookId) {
      setCurrentBookId(book.id);
      const name = [book.title, book.edition].filter(Boolean).join(' ');
      toast(`已切换为《${name}》`);
    }
    close();
  };

  const upload = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    const name = file.name.toLowerCase();
    if (!extensions.some((ext) => name.endsWith(ext))) {
      toast(formatHint);
      return;
    }
    setUploading(true);
    try {
      const uploaded = await api.uploadBook(file);
      const list = await refreshBooks();
      const imported = list.find((book) => book.id === uploaded.id) ?? uploaded;
      setCurrentBookId(imported.id);
      // 解析受限时不自动关闭：这条提示要让用户看清并知道怎么补救，
      // 一闪而过的 toast 做不到（关掉弹窗后信息就没了）。
      if (imported.contentWarning) {
        setWarning({ title: imported.title, text: imported.contentWarning });
        return;
      }
      toast(`《${imported.title}》已上传并识别 ${imported.chapters.length} 个章节`);
      close();
    } catch (error) {
      toast(error.message || '教材上传失败');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="modal open" role="dialog" aria-modal="true" aria-label="选择学习材料" onClick={close}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={close} aria-label="关闭">
          ×
        </button>
        <div className="eyebrow">选择学习材料</div>
        <h2 style={{ marginTop: 7 }}>更换教材</h2>
        {warning && (
          <div className="upload-warning" role="alert">
            <b>《{warning.title}》已导入，但内容可能没被完整读取</b>
            <p>{warning.text}</p>
            <p className="upload-warning-tip">{WARNING_TIP}</p>
            <button type="button" className="warning-ok" onClick={close}>
              知道了，先这样看
            </button>
          </div>
        )}
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
                {/* 提示随教材一起存库，重开弹窗仍然看得到，不用凭记忆回想 */}
                {book.contentWarning ? <em className="choice-warning">⚠ 内容可能没读全</em> : null}
              </span>
              <span>{book.id === currentBookId ? '当前' : '→'}</span>
            </button>
          ))}
          <input
            ref={inputRef}
            className="upload-input"
            type="file"
            accept={accept}
            onChange={upload}
            aria-label="选择教材文件"
          />
          <button className="upload" type="button" onClick={() => inputRef.current?.click()} disabled={uploading}>
            {uploading ? '正在上传并识别目录…' : '＋ 上传新教材（PDF / Word / 文本）'}
          </button>
          <p className="upload-hint">{formatHint}</p>
        </div>
      </div>
    </div>
  );
}
