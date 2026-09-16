import { api } from '../services/api.js';

/**
 * 主页左侧：教材封面卡片 + 下载原文件 + 更换教材按钮。
 *
 * 「下载原文件」只在确实留存了原文件时才出现：老教材（该功能上线前导入的）
 * 没有原文件，给一个必然 404 的链接比没有这个按钮更糟。
 */
export default function BookCard({ book, onSwap }) {
  const { cover, progressText } = book;
  const sourceUrl = api.sourceUrl(book);
  return (
    <div className="book-stage">
      <div className="book-meta">
        <span>正在学习的教材</span>
        <span data-testid="book-progress">{progressText}</span>
      </div>
      <div className="book-orbit" aria-hidden="true">
        <span></span>
        <span></span>
      </div>
      <div className="book-object-wrap">
        <div className="book-object" data-testid="book-cover" aria-label={`${book.title} ${book.edition}`}>
          <div className="tiny">{cover.series}</div>
          <div className="book-title">
            {cover.lines.map((line) => (
              <div key={line}>{line}</div>
            ))}
          </div>
          <div className="formula">
            {cover.formula.map((line) => (
              <div key={line}>{line}</div>
            ))}
          </div>
          <div className="tiny">{cover.footer}</div>
        </div>
      </div>
      <div className="book-actions">
        <button className="switch-book" onClick={onSwap}>
          更换教材
        </button>
        {sourceUrl ? (
          <a className="download-source" href={sourceUrl} download>
            下载原文件
          </a>
        ) : null}
      </div>
    </div>
  );
}
