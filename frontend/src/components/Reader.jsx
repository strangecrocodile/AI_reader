import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import SegmentText from './SegmentText.jsx';

/**
 * 教材原文阅读器：按「纸张」样式渲染段落与公式；
 * 支持拖选原文（onSelect，带所在锚点与选区位置）、锚点定位高亮（focusId），
 * 以及「读到过哪些段落」的可见性上报（onRead），用于计算真实掌握度。
 */
export default function Reader({ content, focusId, onSelect, onRead }) {
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

  // 可见性上报：段落进入视口即算「读过」（同一段只上报一次）
  useEffect(() => {
    if (!onRead || typeof IntersectionObserver === 'undefined') return undefined;
    const nodes = paperRef.current?.querySelectorAll('[data-source-id]');
    if (!nodes?.length) return undefined;
    const reported = new Set();
    const observer = new IntersectionObserver(
      (entries) => {
        const fresh = [];
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const anchorId = entry.target?.dataset?.sourceId;
          if (anchorId && !reported.has(anchorId)) {
            reported.add(anchorId);
            fresh.push(anchorId);
          }
        }
        if (fresh.length) onRead(fresh);
      },
      { threshold: 0.25, rootMargin: '0px 0px -10% 0px' },
    );
    nodes.forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, [content, onRead]);

  const handleMouseUp = () => {
    const sel = window.getSelection();
    const text = sel ? sel.toString().trim() : '';
    const inside = paperRef.current && sel && paperRef.current.contains(sel.anchorNode);
    if (text.length > 1 && inside) {
      onSelect(text, selectionMeta(sel));
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

/** 选区信息：所在原文锚点 + 视口位置（划词气泡据此贴到选区旁边）。 */
function selectionMeta(selection) {
  if (!selection || selection.rangeCount === 0) return { anchorId: '', rect: null };
  const range = selection.getRangeAt(0);
  const node = selection.anchorNode;
  const element = node?.nodeType === 1 ? node : node?.parentElement;
  const sourceElement = element?.closest?.('[data-source-id]');
  const box = range.getBoundingClientRect?.();
  return {
    anchorId: sourceElement?.dataset?.sourceId ?? '',
    rect: box
      ? { top: box.top, left: box.left, bottom: box.bottom, width: box.width }
      : null,
  };
}
