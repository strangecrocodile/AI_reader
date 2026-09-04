/** 主页左侧：教材封面卡片 + 更换教材按钮。 */
export default function BookCard({ book, onSwap }) {
  const { cover, progressText } = book;
  return (
    <div className="book-stage">
      <div className="book-meta">
        <span>正在学习的教材</span>
        <span data-testid="book-progress">{progressText}</span>
      </div>
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
      <button className="switch-book" onClick={onSwap}>
        更换教材　↗
      </button>
    </div>
  );
}
