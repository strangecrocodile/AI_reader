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

/**
 * 划词气泡：选中原文后在选区旁出现的小按钮，点开成为可拖动的追问浮层。
 *
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
    if (!selection?.text) return null;
    return (
      <button
        type="button"
        className="selection-pill"
        style={clampStyle(selection.rect, { x: 0, y: 0 })}
        onClick={onOpen}
        data-testid="selection-bubble"
      >
        问 AI「{selection.truncated}」
      </button>
    );
  }

  const quote = thread?.selectedText || selection?.text || '';
  const messages = thread?.messages ?? [];

  return (
    <section
      className="selection-panel"
      style={clampStyle(anchor ?? selection?.rect, offset)}
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
