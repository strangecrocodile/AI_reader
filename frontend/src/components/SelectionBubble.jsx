import { useCallback, useEffect, useRef, useState } from 'react';
import { Chat } from './CoachPanel.jsx';

const PANEL_WIDTH = 380;
const MARGIN = 8;

/** 把浮层限制在可视区域内，避免拖出屏幕。 */
function clampStyle(anchor, offset) {
  const viewportWidth = typeof window === 'undefined' ? 1280 : window.innerWidth;
  const viewportHeight = typeof window === 'undefined' ? 800 : window.innerHeight;
  const anchorTop = anchor?.bottom ?? anchor?.top ?? 160;
  const anchorLeft = anchor?.left ?? 240;
  const left = Math.min(Math.max(MARGIN, anchorLeft + offset.x), Math.max(MARGIN, viewportWidth - PANEL_WIDTH - MARGIN));
  const top = Math.min(Math.max(MARGIN, anchorTop + 10 + offset.y), Math.max(MARGIN, viewportHeight - 220));
  return { left: `${left}px`, top: `${top}px` };
}

/** 量一下 Range 在**当前视口**里的位置；量不到（无布局，如 jsdom）时返回 null。 */
function measureRange(range) {
  const box = range?.getBoundingClientRect?.();
  if (!box || (box.width === 0 && box.height === 0)) return null;
  return { top: box.top, left: box.left, bottom: box.bottom, width: box.width };
}

/** 选区是否还看得见。量不到布局时一律当作可见，不能凭「没数据」就把界面藏掉。 */
function isVisible(rect) {
  if (!rect) return true;
  const viewportHeight = typeof window === 'undefined' ? 800 : window.innerHeight;
  return rect.bottom > 0 && rect.top < viewportHeight;
}

/**
 * 持续跟踪选区的视口位置。
 *
 * 崩溃点在于「视口坐标只在量到的那一刻有效」：选区时拿到的 `rect` 是当时的视口坐标，
 * 而气泡是 `position: fixed`。用户一滚动，原文移走了，气泡却钉在屏幕上不动——
 * 它看起来还在指着一段早已不在那里的文字。
 *
 * 这里改成存 Range（见 `Reader.selectionMeta`）并在滚动/缩放时重新量。监听用
 * **捕获阶段**：阅读区可能是内层滚动容器，挂在 window 冒泡上的监听收不到它的滚动。
 *
 * 选区滚出视口后停止更新并报告不可见（气泡据此隐藏），滚回来会自动恢复。
 */
function useLiveAnchor(selection) {
  const [rect, setRect] = useState(null);
  const [visible, setVisible] = useState(true);
  const range = selection?.range ?? null;

  useEffect(() => {
    setRect(null);
    setVisible(true);
    if (!range) return undefined;

    const update = () => {
      const measured = measureRange(range);
      if (!measured) return; // 量不到就沿用上一次的结果，别把气泡甩到角落
      const onScreen = isVisible(measured);
      setVisible(onScreen);
      // 滚出视口后**不再更新位置**：气泡本来就隐藏了，而浮层可能正被用户读着，
      // 让它跟着一个看不见的锚点被 clamp 到屏幕边缘，比不跟随更烦人。
      if (onScreen) setRect(measured);
    };

    update();
    window.addEventListener('scroll', update, true);
    window.addEventListener('resize', update);
    return () => {
      window.removeEventListener('scroll', update, true);
      window.removeEventListener('resize', update);
    };
  }, [range]);

  return { rect, visible };
}

/**
 * 划词气泡：选中原文后在选区旁出现的小按钮，点开成为可拖动的追问浮层。
 *
 * - 气泡跟着选区走（滚动/缩放后重新贴合），选区滚出视口时隐藏；
 * - 浮层内的追问都落在同一条 thread 上（由 StudyPage 维护并持久化）；
 * - 拖动只改浮层位置，位置/拖拽状态由前端管理，不入库；
 * - Esc 或右上角 × 关闭。
 */
export default function SelectionBubble({
  selection,
  anchor,
  thread,
  open,
  asking,
  onOpen,
  onClose,
  onAsk,
  onOpenSource,
}) {
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [value, setValue] = useState('');
  const dragRef = useRef(null);
  const { rect: liveRect, visible } = useLiveAnchor(selection);

  // 每次「打开」都从选区位置重新开始
  useEffect(() => {
    if (open) {
      setOffset({ x: 0, y: 0 });
      setValue('');
    }
  }, [open, thread?.id]);

  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => {
      if (event.key === 'Escape') onClose?.();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, onClose]);

  const startDrag = useCallback(
    (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      dragRef.current = { startX: event.clientX, startY: event.clientY, originX: offset.x, originY: offset.y };
      const onMove = (moveEvent) => {
        const drag = dragRef.current;
        if (!drag) return;
        setOffset({
          x: drag.originX + (moveEvent.clientX - drag.startX),
          y: drag.originY + (moveEvent.clientY - drag.startY),
        });
      };
      const onUp = () => {
        dragRef.current = null;
        window.removeEventListener('mousemove', onMove);
        window.removeEventListener('mouseup', onUp);
      };
      window.addEventListener('mousemove', onMove);
      window.addEventListener('mouseup', onUp);
    },
    [offset.x, offset.y],
  );

  const submit = () => {
    const question = value.trim();
    if (!question || asking) return;
    setValue('');
    onAsk?.(question);
  };

  if (!open) {
    // 选区滚出视口就不显示：一个悬在无关文字上方的「问 AI」比没有更让人迷惑
    if (!selection?.text || !visible) return null;
    return (
      <button
        type="button"
        className="selection-pill"
        style={clampStyle(liveRect ?? selection.rect, { x: 0, y: 0 })}
        onClick={onOpen}
        data-testid="selection-bubble"
      >
        问 AI「{selection.truncated}」
      </button>
    );
  }

  const quote = thread?.selectedText || selection?.text || '';
  const messages = thread?.messages ?? [];
  // 浮层打开后跟着选区，但选区滚出视口时停在原地（liveRect 不再更新）——
  // 读答案读到一半让浮层跳到屏幕边缘，比脱钩更烦人。
  const panelAnchor = liveRect ?? anchor ?? selection?.rect;

  return (
    <section
      className="selection-panel"
      style={clampStyle(panelAnchor, offset)}
      data-testid="selection-panel"
      role="dialog"
      aria-label="针对选中原文的追问"
    >
      <header className="selection-panel-head" onMouseDown={startDrag} data-testid="selection-panel-handle">
        <span className="selection-quote" title={quote}>
          {quote ? `「${quote.length > 26 ? `${quote.slice(0, 26)}…` : quote}」` : '本章提问'}
        </span>
        <button className="selection-close" type="button" onClick={onClose} aria-label="关闭追问气泡">
          ×
        </button>
      </header>
      <div className="selection-panel-body">
        {messages.length === 0 ? (
          <p className="selection-hint">就这段原文提问，回答会带上教材依据，可以连续追问。</p>
        ) : (
          <Chat chat={messages} onOpenSource={onOpenSource} />
        )}
      </div>
      <div className="selection-ask">
        <input
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => event.key === 'Enter' && submit()}
          placeholder="继续追问这段原文…"
          aria-label="追问输入框"
        />
        <button type="button" onClick={submit} disabled={asking}>
          {asking ? '思考中…' : '追问'}
        </button>
      </div>
    </section>
  );
}
