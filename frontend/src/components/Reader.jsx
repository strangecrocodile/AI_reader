import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import SegmentText from './SegmentText.jsx';

/**
 * 教材原文阅读器：按「纸张」样式渲染段落与公式；
 * 支持拖选原文（onSelect）、锚点定位高亮（focusId）。
 */
export default function Reader({ content, focusId, onSelect }) {
  const navigate = useNavigate();
  const paperRef = useRef(null);

  // focusId 变化后：滚动到锚点并短暂高亮
  useEffect(() => {
    if (!focusId) return undefined;
    const selector = '#' + (window.CSS?.escape ? CSS.escape(focusId) : focusId);
    const el = paperRef.current?.querySelector(selector);
    el?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
    return undefined;
  }, [focusId]);

  const handleMouseUp = () => {
    const sel = window.getSelection();
    const text = sel ? sel.toString().trim() : '';
    const inside = paperRef.current && sel && paperRef.current.contains(sel.anchorNode);
    if (text.length > 1 && inside) {
      onSelect(text);
    }
  };

  return (
    <article className="reader">
      <div className="reader-top">
        <button className="back" onClick={() => navigate('/')}>
          ← 返回学习计划
        </button>
        <span>{content.intro}</span>
      </div>
      <div
        ref={paperRef}
        className="paper"
        data-testid="paper"
        onMouseUp={handleMouseUp}
        aria-label={`教材第 ${content.page} 页 · ${content.heading}`}
        tabIndex={0}
      >
        <div className="page-num">— {content.page} —</div>
        <h2>{content.heading}</h2>
        {content.paragraphs.map((para, i) =>
          para.type === 'formula' ? (
            <p key={i} className="formula-line">
              {para.parts.map((part, j) =>
                typeof part === 'string' ? (
                  <span key={j}>{part}</span>
                ) : (
                  <sub key={j}>{part.sub}</sub>
                ),
              )}
            </p>
          ) : (
            <p key={i}>
              <SegmentText segs={para.segs} focusId={focusId} />
            </p>
          ),
        )}
      </div>
      <div className="reader-tip">用鼠标左键拖选原文，即可对选中内容提问</div>
    </article>
  );
}
