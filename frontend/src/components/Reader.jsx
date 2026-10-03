import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import ChapterNav from './ChapterNav.jsx';
import ChapterSearch from './ChapterSearch.jsx';
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
  bookId,
  focusId,
  onSelect,
  onRead,
  onPageChange,
  chapters = [],
  currentChapterId,
  onSelectChapter,
  onOpenSource,
  notedAnchorIds,
  viewMode = SCROLL_MODE,
  onViewModeChange,
}) {
  const navigate = useNavigate();
  const paperRef = useRef(null);
  const bodyRef = useRef(null);
  const scrolledForRef = useRef(null);
  const [pageIndex, setPageIndex] = useState(0);
  const [items, setItems] = useState(EMPTY_ITEMS);
  /**
   * 正在读的这一页（原书页码）。
   *
   * 以前这里显示的是 `content.page`——整章的起始页，翻完 76 页它都不会变。现在由
   * 可见段落反推（见下面 onPageChange 那一段），页脚的数字才真的跟着走。
   * 一页内容还没读到时先用章节起始页兜底。
   */
  const [readingPage, setReadingPage] = useState(content.page ?? null);

  const paragraphs = content.paragraphs;
  const paginated = viewMode === PAGE_MODE;

  /** 锚点 → 页码。右侧的「翻译本页」要知道读者正停在哪一页的正文上。 */
  const anchorPages = useMemo(() => {
    const map = new Map();
    for (const para of paragraphs ?? []) {
      const id = anchorIdOf(para);
      if (id && para.page) map.set(id, para.page);
    }
    return map;
  }, [paragraphs]);

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

  // 换章时把页脚的数字先摆回本章起始页，免得上一章的页码停在那儿
  useLayoutEffect(() => {
    setReadingPage(content.page ?? null);
  }, [content]);

  // ---- 可见性上报：段落进入视口即算「读过」（同一段只上报一次） ----
  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') return undefined;
    const nodes = paperRef.current?.querySelectorAll('[data-source-id]');
    if (!nodes?.length) return undefined;
    const order = new Map(Array.from(nodes).map((node, index) => [node, index]));
    const reported = new Set();
    const observer = new IntersectionObserver(
      (entries) => {
        const fresh = [];
        const visible = [];
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const anchorId = entry.target?.dataset?.sourceId;
          if (!anchorId) continue;
          visible.push(anchorId);
          if (!reported.has(anchorId)) {
            reported.add(anchorId);
            fresh.push(anchorId);
          }
        }
        if (fresh.length && onRead) onRead(fresh);
        // 「当前页」取这批可见段落里**最靠前**的那一段所在的页：结构化视图没有真实
        // 页码，读者看的是一列段落，只能这样推。按 DOM 顺序排（不依赖回调顺序）。
        if (visible.length) {
          const first = entries
            .filter((entry) => entry.isIntersecting && entry.target?.dataset?.sourceId)
            .sort((a, b) => (order.get(a.target) ?? 0) - (order.get(b.target) ?? 0))[0];
          const page = anchorPages.get(first?.target?.dataset?.sourceId);
          if (page) {
            setReadingPage(page);
            onPageChange?.(page);
          }
        }
      },
      { threshold: 0.25, rootMargin: '0px 0px -10% 0px' },
    );
    nodes.forEach((node) => observer.observe(node));
    return () => observer.disconnect();
    // current / paginated：分页时换页会改变哪些段落真正可见，需要重新观察
  }, [anchorPages, content, onRead, onPageChange, current, paginated]);

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
  //
  // 纸的高度**不再用内联 magic number 撑**（以前是 `bodyHeight + 130`，那个数是按
  // 页码在顶部时估的）：纸张高度改由内容决定（页眉 + 被裁切的正文 + 页脚页码），
  // 页脚挪到底部之后就永远不会被卡片裁掉或溢出到卡片外。
  const bodyHeight = paginated ? pageClipHeight(items, page, PAGE_HEIGHT) : undefined;
  const bodyShift = paginated ? -(items[page?.start]?.top ?? 0) : 0;

  return (
    <article className="reader">
      <div className="reader-top">
        <button className="back" onClick={() => navigate('/')}>
          ← 返回学习计划
        </button>
        <div className="reader-tools">
          {/* 用路由里的 bookId，而不是 content.bookId：演示数据里没有这个字段，
              拿它去搜会变成「搜 undefined」 */}
          <ChapterSearch
            bookId={bookId}
            currentChapterId={currentChapterId}
            onOpenSource={onOpenSource}
          />
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
        data-testid="paper"
        onMouseUp={handleMouseUp}
        onKeyDown={handleKeyDown}
        aria-label={`教材第 ${content.page} 页 · ${content.heading}`}
        tabIndex={0}
      >
        <h2>{content.heading}</h2>
        <div ref={bodyRef} className="paper-body" style={bodyHeight ? { height: bodyHeight } : undefined}>
          <div
            className="paper-body-inner"
            style={bodyShift ? { transform: `translateY(${bodyShift}px)` } : undefined}
          >
            {paragraphs.map((para, i) => (
              <Paragraph
                key={i}
                para={para}
                index={i}
                focusId={focusId}
                // 锚点 id 必须走 anchorIdOf：正文段落的锚点藏在 segs 里，`para.id` 是空的，
                // 用它判断会让所有文字段落的笔记记号都不显示
                noted={Boolean(notedAnchorIds?.has(anchorIdOf(para)))}
              />
            ))}
          </div>
        </div>
        {/* 页码在**纸的底部**：和纸质书的页脚一样。放顶部时读者的眼睛在段末，
            想看自己在第几页得先往上找；数字跟着正在读的段落走，不再是恒定值。 */}
        <div className="page-num" data-testid="paper-page">
          — {readingPage ?? content.page ?? '—'} —
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

/**
 * 正文里的一个块：段落 / 公式行 / 插图 / 表格。
 *
 * 每个块的根元素都必须带 `data-block-index`——分页装箱是按这些元素**实测的
 * 位置**算的（见 utils/pagination.js），漏一个就会让后续页码整体错位。
 * 类型未知时退回按段落渲染，老数据与将来新增的类型都不会白屏。
 *
 * `noted` 表示这一段有用户笔记，会在段首点一个记号。记号刻意放在锚点 `<span>`
 * **外面**：放进去会被算进划词选中的文本里，用户复制原文时会莫名多出一个符号。
 */
function Paragraph({ para, index, focusId, noted }) {
  const mark = noted ? (
    <span className="note-mark" data-testid={`note-mark-${anchorIdOf(para)}`} title="这一段有你记的笔记" />
  ) : null;

  if (para.type === 'formula') {
    return (
      <p className="formula-line" data-block-index={index}>
        {para.parts.map((part, j) =>
          typeof part === 'string' ? <span key={j}>{part}</span> : <sub key={j}>{part.sub}</sub>,
        )}
      </p>
    );
  }

  if (para.type === 'image') {
    return (
      <figure className="paper-figure" data-block-index={index} data-source-id={para.id}>
        {mark}
        {para.src ? <img src={para.src} alt={para.caption || '教材插图'} loading="lazy" /> : null}
        {para.caption ? <figcaption>{para.caption}</figcaption> : null}
      </figure>
    );
  }

  if (para.type === 'table') {
    return (
      <div className="paper-table" data-block-index={index} data-source-id={para.id}>
        {mark}
        <table>
          <tbody>
            {(para.rows ?? []).map((row, r) => (
              <tr key={r}>
                {row.map((cell, c) =>
                  para.header && r === 0 ? (
                    <th key={c}>{cell}</th>
                  ) : (
                    <td key={c}>{cell}</td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <p data-block-index={index} className={noted ? 'noted' : undefined}>
      {mark}
      <SegmentText segs={para.segs} focusId={focusId} />
    </p>
  );
}

/**
 * 一个块对应的原文锚点 id。
 *
 * 段落把锚点放在最内层的 `src` 片段上（见 SegmentText），插图/表格则直接是 `para.id`。
 * 笔记就是按这个 id 绑定的，所以这里取错会让「这一段有笔记」的记号点错地方。
 */
function anchorIdOf(para) {
  if (para.type === 'image' || para.type === 'table') return para.id ?? '';
  const seg = (para.segs ?? []).find((item) => item && item.t === 'src');
  return seg?.id ?? '';
}

/** 两次测量结果是否一致（1px 内视为没变），避免无谓地重新装箱。 */
function sameLayout(prev, next) {
  if (prev.length !== next.length) return false;
  return prev.every(
    (item, i) =>
      Math.abs(item.top - next[i].top) < 1 && Math.abs(item.bottom - next[i].bottom) < 1,
  );
}

/** 选区信息：所在原文锚点 + 视口位置（划词气泡据此贴到选区旁边）+ 选区本身。 */
function selectionMeta(selection) {
  if (!selection || selection.rangeCount === 0) return { anchorId: '', rect: null, range: null };
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
    // 把 Range 一起交出去：视口坐标在滚动后就作废了，而 Range 还指向同一段原文，
    // 随时可以重新量一次（见 SelectionBubble 的 useLiveAnchor）。
    range,
  };
}
