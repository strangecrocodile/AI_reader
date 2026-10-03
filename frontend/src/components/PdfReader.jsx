import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
// legacy 构建：6.x 用了 `Map.prototype.getOrInsertComputed`，老浏览器上直接打不开
// （连 worker 里也用了，主线程 polyfill 治不了根）。理由详见 utils/pdfAssets.js。
import { GlobalWorkerOptions, TextLayer, getDocument } from 'pdfjs-dist/legacy/build/pdf.mjs';

import {
  matchAnchorForSelection,
  pageAnchorsOf,
  pdfPageOf,
  pdfPageOfAnchor,
} from '../utils/anchorPage.js';
import { PDF_WORKER_URL, pdfAssetOptions } from '../utils/pdfAssets.js';
import ChapterNav from './ChapterNav.jsx';
import ChapterSearch from './ChapterSearch.jsx';
import { PAGE_MODE, SCROLL_MODE } from './Reader.jsx';

// worker 只注册一次；放模块作用域是因为它是全局开关，与哪本书无关
GlobalWorkerOptions.workerSrc = PDF_WORKER_URL;

/** 视口外多远就开始渲染（决定滚动时会不会看到空白页） */
const RENDER_MARGIN = '1200px';
/** 高亮命中的停留时间，与结构化视图的 focusSource 保持一致 */
const HIT_MS = 2200;
/** 缩放档位：1 = 适应宽度 */
const ZOOM_STEPS = [0.75, 1, 1.25, 1.5, 2];
const ZOOM_KEY = 'ai_reader.pdfZoom';

/**
 * 原版 PDF 阅读面：直接渲染上传的那份 PDF。
 *
 * 为什么要有它：结构化视图是把原书「重排」成段落流——矢量插图拿不到（PyMuPDF 只提
 * 位图）、公式只剩一行纯文本、超过 200 页的书表格被跳过、章节粒度粗到 76 页共用
 * 一个页码。教材的观感就是它的内容，重排之后很多页已经不是那本书了。
 *
 * 代价要说清楚：PDF 页面上**没有锚点 id**，而划词提问、笔记、依据回跳都建立在锚点上。
 * 这里靠「页码 + 文本匹配」把选区映射回锚点（utils/anchorPage.js）；匹配不上时锚点
 * 为空串，**提问仍然可用**，只是少掉「这一段就是首条证据」那层加权。
 *
 * 与结构化视图共用同一套对外契约（onSelect / onRead / focusId / 章节导航 / 搜索），
 * 所以 StudyPage、划词气泡、追问线程、笔记、自测那一整块一行都不用改。
 */
export default function PdfReader({
  book,
  sourceUrl,
  content,
  focusId,
  onSelect,
  onRead,
  onPageChange,
  onError,
  notedAnchorIds,
  chapters = [],
  currentChapterId,
  onSelectChapter,
  onOpenSource,
  viewMode = SCROLL_MODE,
  onViewModeChange,
}) {
  const navigate = useNavigate();
  const pageRefs = useRef(new Map());
  const ratiosRef = useRef(new Map());
  const reportedRef = useRef(new Set());
  const [doc, setDoc] = useState(null);
  const [pageCount, setPageCount] = useState(0);
  const [pageSize, setPageSize] = useState(null); // {width, height} = 缩放 1 时的页面尺寸
  const [current, setCurrent] = useState(1);
  const [zoom, setZoom] = useState(() => readZoom());
  const [loadError, setLoadError] = useState('');
  // 没有文字层的页（扫描件）。只在**当前页**是这种页时提示，而不是一见到就常驻提示
  const [noTextPages, setNoTextPages] = useState(() => new Set());

  const pageOffset = content.pageOffset ?? 0;
  const byPage = useMemo(
    () => pageAnchorsOf(content.paragraphs ?? [], pageOffset),
    [content.paragraphs, pageOffset],
  );
  const lastPage = useMemo(() => pdfPageOf(content.pageEnd, pageOffset), [content.pageEnd, pageOffset]);
  // 本页有笔记的记号：不画在原文上（文字层是拼出来的，位置不可靠），只在页角点个数
  const notesByPage = useMemo(() => {
    const counts = new Map();
    if (!notedAnchorIds?.size) return counts;
    for (const [page, entries] of byPage) {
      const count = entries.filter((entry) => notedAnchorIds.has(entry.anchorId)).length;
      if (count) counts.set(page, count);
    }
    return counts;
  }, [byPage, notedAnchorIds]);

  // ---- 载入文档 ----
  useEffect(() => {
    if (!sourceUrl) {
      setLoadError('这本教材没有留存原文件');
      return undefined;
    }
    let cancelled = false;
    const task = getDocument({ url: sourceUrl, ...pdfAssetOptions() });
    task.promise.then(
      async (loaded) => {
        if (cancelled) {
          loaded.destroy();
          return;
        }
        setDoc(loaded);
        setPageCount(loaded.numPages);
        try {
          const first = await loaded.getPage(1);
          const viewport = first.getViewport({ scale: 1 });
          if (!cancelled) setPageSize({ width: viewport.width, height: viewport.height });
        } catch {
          /* 拿不到首页尺寸只影响占位高度，不影响渲染 */
        }
      },
      (error) => {
        if (cancelled) return;
        setLoadError(friendlyLoadError(error));
      },
    );
    return () => {
      cancelled = true;
      task.destroy();
      setDoc(null);
    };
  }, [sourceUrl]);

  useEffect(() => {
    if (loadError) onError?.(loadError);
  }, [loadError, onError]);

  useEffect(() => {
    writeZoom(zoom);
  }, [zoom]);

  // 当前页报给上层：右侧的「翻译本页」要知道读者正停在哪一页。
  //
  // 报的是**段落页码那一套**（= 扫描件的印刷页码），不是 PDF 页序：
  // 后端的段落 `page` 就是印刷页码，翻译按它取正文。两者的差由 pageOffset 承担
  // （见 utils/anchorPage.js 的 pdfPageOf，那边是反着换算）。
  useEffect(() => {
    if (current) onPageChange?.(current + (content.pageOffset ?? 0));
  }, [current, content.pageOffset, onPageChange]);

  // ---- 当前页 + 已读上报 ----
  //
  // 两件事都在 IntersectionObserver 的回调里做。已读上报**不能**放在「依赖 current
  // 的 effect」里：用户打开章节就停在第 1 页，current 一直是 1，setCurrent(1) 不会
  // 引起重渲染，于是第 1 页永远报不上——而那正是最常见的一次上报。
  const onReadRef = useRef(onRead);
  onReadRef.current = onRead;
  const byPageRef = useRef(byPage);
  byPageRef.current = byPage;

  // 换章重来：页码去重集合不清空的话，新章节的第 1 页也会被当成「报过了」
  useEffect(() => {
    reportedRef.current = new Set();
    ratiosRef.current = new Map();
  }, [content]);

  useEffect(() => {
    if (!doc || !pageCount) return undefined;
    // jsdom 没有 IntersectionObserver：没有它就没法知道在看哪一页，
    // 于是停在第一页、也不上报已读——而不是抛错让整个阅读页白屏。
    if (typeof IntersectionObserver === 'undefined') return undefined;
    const ratios = ratiosRef.current;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          ratios.set(Number(entry.target.dataset.page), entry.intersectionRatio);
        }
        let best = 0;
        let bestRatio = 0;
        for (const [page, ratio] of ratios) {
          if (ratio > bestRatio) {
            best = page;
            bestRatio = ratio;
          }
        }
        if (best) setCurrent(best);

        const report = onReadRef.current;
        if (!report) return;
        const fresh = [];
        for (const [page, ratio] of ratios) {
          if (ratio <= 0.25 || reportedRef.current.has(page)) continue;
          reportedRef.current.add(page);
          fresh.push(page);
        }
        if (!fresh.length) return;
        const anchors = [];
        for (const page of fresh) {
          for (const entry of byPageRef.current.get(page) ?? []) anchors.push(entry.anchorId);
        }
        if (anchors.length) report(anchors);
      },
      { threshold: [0, 0.25, 0.5, 0.75, 1] },
    );
    for (const node of pageRefs.current.values()) observer.observe(node);
    return () => observer.disconnect();
  }, [doc, pageCount, viewMode]);

  // ---- 定位：锚点 → 页 → 高亮 ----
  const hitTimer = useRef(null);
  useEffect(() => {
    if (!focusId || !doc) return undefined;
    const page = pdfPageOfAnchor(byPage, focusId);
    if (!page) return undefined;
    const node = pageRefs.current.get(page);
    node?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
    setCurrent(page);
    // 等这一页的文字层渲染完再上高亮（span 是异步出现的）
    let tries = 0;
    const timer = setInterval(() => {
      tries += 1;
      if (highlightAnchor(node, byPage.get(page) ?? [], focusId) || tries > 20) {
        clearInterval(timer);
        clearTimeout(hitTimer.current);
        hitTimer.current = setTimeout(() => clearHits(node), HIT_MS);
      }
    }, 120);
    return () => {
      clearInterval(timer);
      clearTimeout(hitTimer.current);
    };
  }, [focusId, doc, byPage]);

  useEffect(
    () => () => {
      clearTimeout(hitTimer.current);
    },
    [],
  );

  const goToPage = useCallback(
    (page) => {
      const target = Math.min(Math.max(page, 1), pageCount || 1);
      pageRefs.current.get(target)?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
      setCurrent(target);
    },
    [pageCount],
  );

  /** 某一页渲染完了。没文字层的页记下来，好在当前页是它时给一句提示。 */
  const handleRendered = useCallback((page, hasText) => {
    setNoTextPages((prev) => {
      if (prev.has(page) === !hasText) return prev; // 状态没变就别触发重渲染
      const next = new Set(prev);
      if (hasText) next.delete(page);
      else next.add(page);
      return next;
    });
  }, []);

  const handleKeyDown = (event) => {
    const keys = { ArrowRight: 1, PageDown: 1, ArrowLeft: -1, PageUp: -1 };
    const step = keys[event.key];
    if (!step) return;
    event.preventDefault();
    goToPage(current + step);
  };

  /**
   * 划词 → 锚点。
   *
   * 与结构化视图同一个 `onSelect(text, meta)` 契约：`meta.anchorId` 认不出来时是
   * 空串，后端对空锚点本来就有降级路径（`ask._pinned_evidence` 直接跳过），
   * 所以「问 AI」这条路不会因为认不出锚点而断掉。
   */
  const handleMouseUp = () => {
    const sel = window.getSelection();
    const text = sel ? sel.toString().trim() : '';
    if (text.length < 2 || !sel.rangeCount) return;
    const node = sel.anchorNode;
    const element = node?.nodeType === 1 ? node : node?.parentElement;
    const pageNode = element?.closest?.('[data-page]');
    if (!pageNode) return;
    const page = Number(pageNode.dataset.page);
    const match = matchAnchorForSelection(byPage, page, text);
    const box = sel.getRangeAt(0).getBoundingClientRect?.();
    onSelect?.(text, {
      anchorId: match.anchorId,
      rect: box
        ? { top: box.top, left: box.left, bottom: box.bottom, width: box.width }
        : null,
      range: sel.getRangeAt(0),
      page,
    });
  };

  const single = viewMode === PAGE_MODE;
  const width = pageSize ? Math.round(pageSize.width * zoom) : 820;

  if (loadError) {
    // 回退到结构化视图由 StudyPage 决定；这里给一句可读的说明，不留白屏
    return (
      <article className="reader">
        <p className="pdf-note">原版 PDF 打不开（{loadError}），已切回结构化视图。</p>
      </article>
    );
  }

  return (
    <article
      className="reader pdf-reader"
      onKeyDown={handleKeyDown}
      tabIndex={0}
      aria-label={`原版教材 · ${content.heading}`}
    >
      <div className="reader-top">
        <button className="back" onClick={() => navigate('/')}>
          ← 返回学习计划
        </button>
        <div className="reader-tools">
          <ChapterSearch
            bookId={book?.id}
            currentChapterId={currentChapterId}
            onOpenSource={onOpenSource}
          />
          <ChapterNav chapters={chapters} currentId={currentChapterId} onSelect={onSelectChapter} />
          <div className="view-mode" role="group" aria-label="阅读方式">
            <button
              type="button"
              className={single ? '' : 'active'}
              aria-pressed={!single}
              onClick={() => onViewModeChange?.(SCROLL_MODE)}
            >
              滚动
            </button>
            <button
              type="button"
              className={single ? 'active' : ''}
              aria-pressed={single}
              onClick={() => onViewModeChange?.(PAGE_MODE)}
            >
              分页
            </button>
          </div>
        </div>
      </div>

      {noTextPages.has(current) ? (
        <p className="pdf-note">
          第 {current} 页是扫描图片，页面上没有可选中的文字——这一页的划词提问请切到
          「结构化」视图，那里是识别出来的文本。问答与溯源不受影响。
        </p>
      ) : null}

      <div
        className={`pdf-pages${single ? ' pdf-single' : ''}`}
        onMouseUp={handleMouseUp}
        data-testid="pdf-pages"
      >
        {Array.from({ length: pageCount }, (_, index) => index + 1).map((page) => (
          <PdfPage
            key={page}
            page={page}
            doc={doc}
            scale={zoom}
            pageSize={pageSize}
            active={!single || page === current}
            width={width}
            noteCount={notesByPage.get(page) ?? 0}
            onRendered={handleRendered}
            pageRefCallback={(node) => {
              if (node) pageRefs.current.set(page, node);
              else pageRefs.current.delete(page);
            }}
          />
        ))}
      </div>

      {/* 页码与翻页放在**最下面**：读书时眼睛在页面底部，页码就该在那儿，
          和纸质书的页脚一样；顶部留出来只放「去哪儿」的工具。 */}
      <div className="pdf-bar">
        <button type="button" onClick={() => goToPage(current - 1)} disabled={current <= 1}>
          ← 上一页
        </button>
        <span className="page-count">
          第
          <input
            className="pdf-page-input"
            aria-label="跳转到页"
            value={current}
            onChange={(event) => {
              const value = Number(event.target.value.replace(/\D/g, ''));
              if (value) goToPage(value);
            }}
          />
          / {pageCount || '…'} 页
        </span>
        <button
          type="button"
          onClick={() => goToPage(current + 1)}
          disabled={!pageCount || current >= pageCount}
        >
          下一页 →
        </button>
        <span className="pdf-spacer" />
        {lastPage ? (
          <span title="本章在原书里覆盖的页范围">
            本章第 {content.page}–{content.pageEnd} 页
          </span>
        ) : null}
        <button
          type="button"
          onClick={() => setZoom(stepZoom(zoom, -1))}
          disabled={zoom <= ZOOM_STEPS[0]}
          aria-label="缩小"
        >
          −
        </button>
        <span className="pdf-zoom">{Math.round(zoom * 100)}%</span>
        <button
          type="button"
          onClick={() => setZoom(stepZoom(zoom, 1))}
          disabled={zoom >= ZOOM_STEPS[ZOOM_STEPS.length - 1]}
          aria-label="放大"
        >
          ＋
        </button>
      </div>

      <div className="reader-tip">
        {single
          ? '分页模式：一次一页，用「上一页 / 下一页」或 ← → 方向键翻页'
          : '原版页面：拖动滚动，用鼠标左键拖选原文即可对选中内容提问'}
      </div>
    </article>
  );
}

/**
 * 一页 PDF：先把 canvas 画出来，再叠一层可选择的文字。
 *
 * 渲染时机交给 IntersectionObserver（离视口 1200px 就开始画），所以一本 400 页的书
 * 只画你正在看的几页；离开视口后**不销毁**——销毁再重建会让来回滚动变得很卡，
 * 而 canvas 占的是显存/内存，几页的量级完全承受得起。
 */
function PdfPage({
  page,
  doc,
  scale,
  pageSize,
  width,
  active,
  noteCount,
  onRendered,
  pageRefCallback,
}) {
  const holderRef = useRef(null);
  const canvasRef = useRef(null);
  const textRef = useRef(null);
  const [render, setRender] = useState(false);
  const [failed, setFailed] = useState(false);
  // 回调走 ref：调用方每渲染一次就会给出新的函数引用，直接放进依赖会让
  // 「渲染完 → 上报 → 父组件重渲染 → 依赖变化 → 再渲染」转成死循环。
  const renderedRef = useRef(onRendered);
  renderedRef.current = onRendered;
  const refCallbackRef = useRef(pageRefCallback);
  refCallbackRef.current = pageRefCallback;

  useEffect(() => {
    const node = holderRef.current;
    refCallbackRef.current?.(node);
    return () => refCallbackRef.current?.(null);
  }, []);

  useEffect(() => {
    if (render || !doc) return undefined;
    const node = holderRef.current;
    if (!node || typeof IntersectionObserver === 'undefined') {
      setRender(true);
      return undefined;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setRender(true);
          observer.disconnect();
        }
      },
      { rootMargin: RENDER_MARGIN },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [doc, render]);

  useEffect(() => {
    if (!render || !doc) return undefined;
    let cancelled = false;
    let layer = null;
    (async () => {
      try {
        const pdfPage = await doc.getPage(page);
        if (cancelled) return;
        const viewport = pdfPage.getViewport({ scale });
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        canvas.width = Math.floor(viewport.width * ratio);
        canvas.height = Math.floor(viewport.height * ratio);
        canvas.style.width = `${Math.floor(viewport.width)}px`;
        canvas.style.height = `${Math.floor(viewport.height)}px`;
        await pdfPage.render({
          canvasContext: canvas.getContext('2d'),
          viewport,
          transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
        }).promise;
        if (cancelled) return;

        // 文字层：不画字（CSS 里是透明的），只提供可选中、可定位的 span
        const container = textRef.current;
        if (!container) return;
        container.textContent = '';
        const textContent = await pdfPage.getTextContent();
        if (cancelled) return;
        layer = new TextLayer({ textContentSource: textContent, container, viewport });
        await layer.render();
        const hasText = (textContent.items ?? []).some((item) => (item.str ?? '').trim());
        if (!cancelled) renderedRef.current?.(page, hasText);
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
      try {
        layer?.cancel?.();
      } catch {
        /* 取消失败无所谓：组件已经在卸载 */
      }
    };
  }, [render, doc, page, scale]);

  // 未渲染时按第 1 页的比例占位，避免滚动时高度跳变
  const placeholder = pageSize
    ? { paddingTop: `${(pageSize.height / pageSize.width) * 100}%` }
    : { minHeight: '600px' };

  return (
    <div
      ref={holderRef}
      className={`pdf-page${active ? ' current' : ''}`}
      data-page={page}
      style={{ width: `${width}px`, maxWidth: '100%', '--scale-factor': scale }}
    >
      {noteCount ? (
        <span className="pdf-note-mark" title={`本页有 ${noteCount} 条笔记`}>
          {noteCount}
        </span>
      ) : null}
      {failed ? (
        <p className="pdf-page-error">第 {page} 页渲染失败（文件可能损坏或加密）</p>
      ) : render ? (
        <>
          <canvas ref={canvasRef} aria-label={`原书第 ${page} 页`} />
          <div ref={textRef} className="textLayer" />
        </>
      ) : (
        <div style={placeholder} aria-hidden="true" />
      )}
    </div>
  );
}

/** 高亮 anchors 里命中的那些 span：按归一化文本匹配，找到几个标几个。 */
function highlightAnchor(pageNode, anchors, focusId) {
  if (!pageNode) return false;
  const target = anchors.find((entry) => entry.anchorId === focusId);
  const container = pageNode.querySelector('.textLayer');
  if (!target || !container) return false;
  const spans = Array.from(container.querySelectorAll('span'));
  if (!spans.length) return false;
  const pageText = spans.map((span) => span.textContent ?? '').join('');
  if (!pageText) return false;
  const needle = target.normalized.slice(0, 24);
  if (!needle) return false;
  let hit = 0;
  for (const span of spans) {
    if (normalizeSpan(span.textContent ?? '').includes(needle.slice(0, 8))) {
      span.classList.add('pdf-hit');
      hit += 1;
    }
  }
  return hit > 0;
}

function clearHits(pageNode) {
  pageNode?.querySelectorAll?.('.pdf-hit').forEach((node) => node.classList.remove('pdf-hit'));
}

function normalizeSpan(value) {
  return String(value ?? '')
    .replace(/[\s\u3000]+/g, '')
    .replace(/[-\u2010-\u2015]/g, '');
}

function stepZoom(zoom, direction) {
  const index = ZOOM_STEPS.indexOf(zoom);
  const next = (index === -1 ? 1 : index) + direction;
  return ZOOM_STEPS[Math.min(Math.max(next, 0), ZOOM_STEPS.length - 1)];
}

function readZoom() {
  try {
    const value = Number(window.localStorage.getItem(ZOOM_KEY));
    return ZOOM_STEPS.includes(value) ? value : 1;
  } catch {
    return 1;
  }
}

function writeZoom(zoom) {
  try {
    window.localStorage.setItem(ZOOM_KEY, String(zoom));
  } catch {
    /* 隐私模式下写不了，不影响阅读 */
  }
}

function friendlyLoadError(error) {
  const name = error?.name ?? '';
  if (name === 'PasswordException') return '文件有密码';
  if (name === 'InvalidPDFException') return '文件不是有效的 PDF';
  if (name === 'MissingPDFException') return '原文件已不在服务器上';
  return error?.message || '读取失败';
}
