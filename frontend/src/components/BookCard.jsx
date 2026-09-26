import { api } from '../services/api.js';

/**
 * 主页左侧：教材封面卡片 + 下载原文件 / 导出 Markdown + 更换教材按钮。
 *
 * 「下载原文件」只在确实留存了原文件时才出现：老教材（该功能上线前导入的）
 * 没有原文件，给一个必然 404 的链接比没有这个按钮更糟。
 *
 * 「导出 Markdown」是另一条路，**不依赖原文件**：它是从库里现渲染的，段落带
 * `<!-- page: N -->`，所以老教材也能导出。这个接口一直存在，但过去只能用 curl 调
 * ——功能做完了，界面上却没有入口，等于白做。
 */
export default function BookCard({ book, onSwap }) {
  const { cover, progressText } = book;
  const sourceUrl = api.sourceUrl(book);
  const markdownUrl = api.markdownUrl(book);
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
        <div className="book-object" data-testid="book-cover" aria-label={[book.title, book.edition].filter(Boolean).join(' ')}>
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
        {markdownUrl ? (
          <a className="download-source" href={markdownUrl} download>
            导出 Markdown
          </a>
        ) : null}
      </div>
    </div>
  );
}
