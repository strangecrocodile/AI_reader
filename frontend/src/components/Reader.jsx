import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import ChapterNav from './ChapterNav.jsx';
import SegmentText from './SegmentText.jsx';
import {
  PAGE_HEIGHT,
  blockIndexOfAnchor,
  packIntoPages,
  pageClipHeight,
  pageIndexForBlock,
} from '../utils/pagination.js';

/** 阅读方式：整章连续滚动 / 按纸张分页。 */
export const SCROLL_MODE = 'scroll';
export const PAGE_MODE = 'page';

/** 未测量时的占位：必须是稳定引用，否则每轮渲染都会触发重新装箱。 */
const EMPTY_ITEMS = [];

/**
 * 教材原文阅读器：按「纸张」样式渲染段落与公式。
 *
 * 提供两种阅读方式（顶部可切换）：
 * - 滚动：整章连续滚动，适合快速浏览；
 * - 分页：按实测段落高度切页，一次一页，翻页按钮 / ←→ 方向键翻页，
 *   更接近翻教材的感觉，也避免一口气滑过整章。
 *
 * 两种模式**渲染的是同一份 DOM**，只是分页模式下由外层做裁切 + 位移，
 * 因此划词选中、锚点定位高亮、可见性上报（onRead）在两种模式下行为一致，
 * 不会出现「换了阅读方式就选不中原文」这类分叉。
 *
 * 另支持拖选原文（onSelect，带所在锚点与选区位置）、锚点定位高亮（focusId），
 * 以及「读到过哪些段落」的可见性上报（onRead），用于计算真实掌握度。
 */
export default function Reader({
  content,
  focusId,
  onSelect,
  onRead,
  chapters = [],
  currentChapterId,
  onSelectChapter,
  viewMode = SCROLL_MODE,
  onViewModeChange,
}) {
  const navigate = useNavigate();
  const paperRef = useRef(null);
  const bodyRef = useRef(null);
  const scrolledForRef = useRef(null);
  const [pageIndex, setPageIndex] = useState(0);
  const [items, setItems] = useState(EMPTY_ITEMS);

  const paragraphs = content.paragraphs;
  const paginated = viewMode === PAGE_MODE;

  const pages = useMemo(() => packIntoPages(items, PAGE_HEIGHT), [items]);
  const totalPages = pages.length;
  // 换章后页数可能变少：夹住页码，而不是渲染一片空白
  const current = Math.min(pageIndex, totalPages - 1);
  const page = pages[current];
  const anchorBlock = useMemo(
    () => blockIndexOfAnchor(paragraphs, focusId),
    [paragraphs, focusId],
  );

  /**
   * 量出每个块相对正文区顶部的位置。
   *
   * 用 `bottom` 而不是 `height`：段落间有外边距，`height` 不含外边距，
   * 累加高度会和真实位置越差越远。位移（translateY）对父子元素是等量的，
   * 因此分页模式下的测量结果同样有效，不必先切回滚动模式再量。
   */
  const measure = useCallback(() => {
    const body = bodyRef.current;
    const nodes = body?.querySelectorAll('[data-block-index]');
    if (!body || !nodes?.length) return;
    const base = body.getBoundingClientRect().top;
    const next = Array.from(nodes, (node) => {
      const rect = node.getBoundingClientRect();
      return { top: rect.top - base, bottom: rect.bottom - base };
    });
    setItems((prev) => (sameLayout(prev, next) ? prev : next));
  }, []);

  useLayoutEffect(() => {
    measure();
  }, [measure, content]);

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  }, [measure]);

  // 换章回到第一页；锚点变化时允许重新滚动一次
  useLayoutEffect(() => {
    setPageIndex(0);
    scrolledForRef.current = null;
  }, [content]);

  useEffect(() => {
    scrolledForRef.current = null;
  }, [focusId]);

  // focusId 指向的段落不在当前页时，先翻到它所在的页
  useEffect(() => {
    if (!focusId || !paginated || anchorBlock < 0) return;
    setPageIndex(pageIndexForBlock(pages, anchorBlock));
  }, [focusId, paginated, anchorBlock, pages]);

  // focusId 变化后：滚动到锚点并短暂高亮
  useEffect(() => {
    if (!focusId) return undefined;
    // 分页模式下锚点可能被裁在别的页：等翻过去再滚，否则滚到一个看不见的元素上
    if (paginated && anchorBlock >= 0 && pageIndexForBlock(pages, anchorBlock) !== current) {
      return undefined;
    }
    if (scrolledForRef.current === focusId) return undefined;
    scrolledForRef.current = focusId;
    const selector = '#' + (window.CSS?.escape ? CSS.escape(focusId) : focusId);
    const el = paperRef.current?.querySelector(selector);
    el?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
    return undefined;
  }, [focusId, paginated, anchorBlock, pages, current]);

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
    // current / paginated：分页时换页会改变哪些段落真正可见，需要重新观察
  }, [content, onRead, current, paginated]);

  const goToPage = useCallback(
    (index) => {
      setPageIndex(Math.min(Math.max(index, 0), totalPages - 1));
    },
    [totalPages],
  );

  const handleKeyDown = (event) => {
    if (!paginated || totalPages <= 1) return;
    const keys = { ArrowRight: 1, PageDown: 1, ArrowLeft: -1, PageUp: -1 };
    const step = keys[event.key];
    if (!step) return;
    event.preventDefault();
    goToPage(current + step);
  };

  const handleMouseUp = () => {
    const sel = window.getSelection();
    const text = sel ? sel.toString().trim() : '';
    const inside = paperRef.current && sel && paperRef.current.contains(sel.anchorNode);
    if (text.length > 1 && inside) {
      onSelect(text, selectionMeta(sel));
    }
  };

  // 分页模式：外层裁切成「一页高」，内层整体上移，把当前页顶到最上面。
  // 位移为 0 时不加 transform——多层空 transform 会平白多出一层包含块。
  const bodyHeight = paginated ? pageClipHeight(items, page, PAGE_HEIGHT) : undefined;
  const bodyShift = paginated ? -(items[page?.start]?.top ?? 0) : 0;

  return (
    <article className="reader">
      <div className="reader-top">
        <button className="back" onClick={() => navigate('/')}>
          ← 返回学习计划
        </button>
        <div className="reader-tools">
          <ChapterNav
            chapters={chapters}
            currentId={currentChapterId}
            onSelect={onSelectChapter}
          />
          <div className="view-mode" role="group" aria-label="阅读方式">
            <button
              type="button"
              className={paginated ? '' : 'active'}
              aria-pressed={!paginated}
              onClick={() => onViewModeChange?.(SCROLL_MODE)}
            >
              滚动
            </button>
            <button
              type="button"
              className={paginated ? 'active' : ''}
              aria-pressed={paginated}
              onClick={() => onViewModeChange?.(PAGE_MODE)}
            >
              分页
            </button>
          </div>
        </div>
      </div>
      <p className="reader-intro">{content.intro}</p>
      <div
        ref={paperRef}
        className={`paper${paginated ? ' paginated' : ''}`}
        style={paginated ? { height: `calc(${bodyHeight}px + 130px)` } : undefined}
        data-testid="paper"
        onMouseUp={handleMouseUp}
        onKeyDown={handleKeyDown}
        aria-label={`教材第 ${content.page} 页 · ${content.heading}`}
        tabIndex={0}
      >
        <div className="page-num">— {content.page} —</div>
        <h2>{content.heading}</h2>
        <div ref={bodyRef} className="paper-body" style={bodyHeight ? { height: bodyHeight } : undefined}>
          <div
            className="paper-body-inner"
            style={bodyShift ? { transform: `translateY(${bodyShift}px)` } : undefined}
          >
            {paragraphs.map((para, i) =>
              para.type === 'formula' ? (
                <p key={i} className="formula-line" data-block-index={i}>
                  {para.parts.map((part, j) =>
                    typeof part === 'string' ? (
                      <span key={j}>{part}</span>
                    ) : (
                      <sub key={j}>{part.sub}</sub>
                    ),
                  )}
                </p>
              ) : (
                <p key={i} data-block-index={i}>
                  <SegmentText segs={para.segs} focusId={focusId} />
                </p>
              ),
            )}
          </div>
        </div>
      </div>
      {paginated && (
        <div className="page-bar">
          <button type="button" onClick={() => goToPage(current - 1)} disabled={current <= 0}>
            ← 上一页
          </button>
          <span className="page-count">
            第 {current + 1} / {totalPages} 页
          </span>
          <button
            type="button"
            onClick={() => goToPage(current + 1)}
            disabled={current >= totalPages - 1}
          >
            下一页 →
          </button>
        </div>
      )}
      <div className="reader-tip">
        {paginated
          ? '分页模式：用「上一页 / 下一页」或 ← → 方向键翻页'
          : '用鼠标左键拖选原文，即可对选中内容提问'}
      </div>
    </article>
  );
}

/** 两次测量结果是否一致（1px 内视为没变），避免无谓地重新装箱。 */
function sameLayout(prev, next) {
  if (prev.length !== next.length) return false;
  return prev.every(
    (item, i) =>
      Math.abs(item.top - next[i].top) < 1 && Math.abs(item.bottom - next[i].bottom) < 1,
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
