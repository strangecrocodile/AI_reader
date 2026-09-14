/**
 * 章节导航：上一章 / 目录下拉 / 下一章。
 *
 * 补齐「上传一本教材后只能看到第一章，找不到怎么翻到下一章」这个缺口：
 * 阅读器过去只渲染当前章节，页面上没有任何通往其他章节的入口。
 *
 * 组件本身不取数据——章节列表由 StudyPage 从 BookContext 拿（和主页共用同一份
 * 数据，不额外发请求），这里只负责渲染与回调，方便单测。
 */
export default function ChapterNav({ chapters = [], currentId, onSelect }) {
  const index = chapters.findIndex((chapter) => chapter.id === currentId);
  const prev = index > 0 ? chapters[index - 1] : null;
  const next = index >= 0 && index < chapters.length - 1 ? chapters[index + 1] : null;

  if (!chapters.length) return null;

  // 按钮在首 / 末章是禁用的，但仍显式判空：`prev.id` 这种写法一旦在别处被
  // 触发（键盘、测试里直接派发事件）就是凭空一个 TypeError。
  const go = (chapter) => {
    if (chapter) onSelect?.(chapter.id);
  };

  return (
    <nav className="chapter-nav" aria-label="章节导航">
      <button
        type="button"
        className="nav-btn"
        onClick={() => go(prev)}
        disabled={!prev}
        title={prev ? prev.title : '已经是第一章'}
      >
        ← 上一章
      </button>
      <select
        className="chapter-select"
        aria-label="选择章节"
        value={index >= 0 ? currentId : ''}
        onChange={(event) => onSelect?.(event.target.value)}
      >
        {/* 章节不在列表里时（例如从知识地图跳进来）也让下拉有个合法初值 */}
        {index < 0 && <option value="">选择章节…</option>}
        {chapters.map((chapter) => (
          <option key={chapter.id} value={chapter.id}>
            {chapter.num ? `${chapter.num} · ` : ''}
            {chapter.title}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="nav-btn"
        onClick={() => go(next)}
        disabled={!next}
        title={next ? next.title : '已经是最后一章'}
      >
        下一章 →
      </button>
    </nav>
  );
}
