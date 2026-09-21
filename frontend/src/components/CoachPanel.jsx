import { useState } from 'react';
import SegmentText from './SegmentText.jsx';

/**
 * AI 讲解侧栏：顶部 Tab（AI 讲解 / 知识点大纲）+ 讲解内容 + 追问线程与问答区。
 * 顶部还展示由学习事件算出的掌握度及其构成（见 services/progress.js）。
 */
export default function CoachPanel({
  content,
  thread,
  threads = [],
  asking,
  selected,
  progress,
  onAsk,
  onComplete,
  onSelectThread,
  onDeleteThread,
  onOpenSource,
  clearSelected,
  onFocusSource,
}) {
  const [tab, setTab] = useState('explain');

  return (
    <aside className="coach">
      <div className="coach-head">
        <div className="eyebrow">本章学习助手</div>
        <h2>{content.heading}</h2>
        <MasteryPanel progress={progress} onComplete={onComplete} />
        <div className="tabs" role="tablist">
          <button className={`tab${tab === 'explain' ? ' active' : ''}`} onClick={() => setTab('explain')} role="tab">
            AI 讲解
          </button>
          <button className={`tab${tab === 'outline' ? ' active' : ''}`} onClick={() => setTab('outline')} role="tab">
            知识点大纲
          </button>
        </div>
      </div>
      <div className="coach-scroll">
        {tab === 'explain' ? (
          <div className="tab-content" role="tabpanel">
            {content.knowledgePoints.map((kp) =>
              kp.kind === 'example' ? (
                <div key={kp.id} className="example">
                  <b>{kp.title}</b>
                  <br />
                  <SegmentText segs={kp.body} />
                </div>
              ) : (
                <div key={kp.id} className="explain-card">
                  <h3>{kp.title}</h3>
                  <p>
                    <SegmentText segs={kp.body} />
                  </p>
                  {kp.sourceId && (
                    <button className="link-source" onClick={() => onFocusSource(kp.sourceId, kp.sourceLabel)}>
                      {kp.sourceLabel}　↙
                    </button>
                  )}
                </div>
              ),
            )}
          </div>
        ) : (
          <div className="tab-content" role="tabpanel">
            {content.outline.map((item) => (
              <button key={item.index} className="outline-item" onClick={() => onFocusSource(item.sourceId)}>
                <span className="outline-index">{item.index}</span>
                <span>
                  <strong>{item.title}</strong>
                  <p>{item.summary}</p>
                </span>
              </button>
            ))}
          </div>
        )}
        <ThreadList threads={threads} activeId={thread?.id} onSelect={onSelectThread} onDelete={onDeleteThread} />
        <Chat chat={thread?.messages ?? []} onOpenSource={onOpenSource} />
      </div>
      <AskBox
        selected={selected}
        thread={thread}
        asking={asking}
        onAsk={onAsk}
        onClear={clearSelected}
      />
    </aside>
  );
}

/** 追问线程列表：点标题切换并定位回它绑定的原文，× 删除。 */
export function ThreadList({ threads = [], activeId, onSelect, onDelete }) {
  if (threads.length === 0) return null;
  return (
    <div className="thread-list" data-testid="thread-list">
      <div className="thread-list-head">
        <span>追问线程</span>
        <span>{threads.length} 条</span>
      </div>
      <ul>
        {threads.map((thread) => (
          <li key={thread.id} className={thread.id === activeId ? 'active' : ''}>
            <button className="thread-open" type="button" onClick={() => onSelect?.(thread.id)}>
              <span className="thread-title">{thread.title}</span>
              <span className="thread-meta">{(thread.messages ?? []).length} 条消息</span>
            </button>
            <button
              className="thread-delete"
              type="button"
              onClick={() => onDelete?.(thread.id)}
              aria-label={`删除线程 ${thread.title}`}
            >
              ×
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** 掌握度面板：数值 + 构成拆分 + 学习信号，全部来自真实事件。 */
export function MasteryPanel({ progress, onComplete }) {
  if (!progress) return null;
  const { mastery, status, breakdown = [], signals = {}, note } = progress;
  const statusText = status === 'learned' ? '已掌握' : status === 'learning' ? '学习中' : '待学习';

  return (
    <div className="mastery" data-testid="mastery-panel">
      <div className="mastery-head">
        <strong className="mastery-value">掌握度 {mastery}%</strong>
        <span className={`mastery-status ${status}`}>{statusText}</span>
      </div>
      <span className="mastery-track" aria-hidden="true">
        <i style={{ width: `${mastery}%` }} />
      </span>
      <ul className="mastery-breakdown" title={note}>
        {breakdown.map((item) => (
          <li key={item.key}>
            <span>{item.label}</span>
            <span className="mastery-part">
              {item.weight ? `${item.score} / ${item.weight}` : '未计入'}
            </span>
          </li>
        ))}
      </ul>
      <p className="mastery-signals">
        已读 {signals.paragraphsRead}/{signals.paragraphsTotal} 段 · 提问 {signals.askCount} 次
        {signals.quizCount
          ? ` · 自测 ${signals.quizCount} 题（正确率 ${Math.round((signals.quizAccuracy ?? 0) * 100)}%）`
          : ''}
      </p>
      {status !== 'learned' && onComplete && (
        <button className="mastery-complete" onClick={onComplete}>
          标记本章学完
        </button>
      )}
    </div>
  );
}

/**
 * 问答对话流：用户气泡 + AI 回答（流式逐块显示，结束后带教材依据锚点）。
 * 依据可能来自其他章节，此时按钮会标出章节名，点击由 onOpenSource 决定是定位还是跳章。
 */
export function Chat({ chat, onOpenSource }) {
  if (chat.length === 0) return null;
  return (
    <div className="chat show" data-testid="chat" aria-live="polite">
      {chat.map((msg, i) =>
        msg.role === 'user' ? (
          <div key={i} className="bubble user-bubble">
            {msg.text}
            {msg.context && <small className="ctx-note">{msg.context}</small>}
          </div>
        ) : (
          <div
            key={i}
            className="bubble answer"
            data-testid="answer"
            data-streaming={msg.streaming ? 'true' : undefined}
          >
            <b>AI讲师</b>
            <br />
            {msg.text || (msg.streaming ? '正在思考…' : '')}
            {msg.streaming && msg.text && <span className="stream-caret" aria-hidden="true" />}
            {msg.scope === 'book' && !msg.streaming && (
              <small className="scope-note">依据取自全书，含其他章节的段落</small>
            )}
            {msg.sources?.length > 0 && (
              <div className="answer-sources">
                {msg.sources.map((sid) => (
                  <button
                    key={sid}
                    className={`source-chip${isCrossChapter(sid, msg.sourceDetails) ? ' cross' : ''}`}
                    onClick={() => onOpenSource(sid, findDetail(sid, msg.sourceDetails))}
                  >
                    {sourceLabel(sid, msg.sourceDetails)} ↖
                  </button>
                ))}
              </div>
            )}
          </div>
        ),
      )}
    </div>
  );
}

function findDetail(sourceId, details = []) {
  return details.find((item) => item.id === sourceId);
}

function isCrossChapter(sourceId, details = []) {
  return Boolean(findDetail(sourceId, details)?.crossChapter);
}

function sourceLabel(sourceId, details = []) {
  const detail = findDetail(sourceId, details);
  if (detail?.page) {
    const chapter = detail.crossChapter && detail.chapterTitle ? `${detail.chapterTitle} · ` : '';
    return `教材依据 · ${chapter}第 ${detail.page} 页`;
  }
  return `教材依据 ${sourceId.replace('source-', '#')}`;
}

/** 提问框：显示已选中原文，支持回车提问。 */
export function AskBox({ selected, thread, asking, onAsk, onClear }) {
  const [value, setValue] = useState('');

  const submit = () => {
    const q = value.trim();
    if (!q || asking) return;
    onAsk(q);
    setValue('');
  };

  const placeholder = selected
    ? '围绕这段原文提问…'
    : thread?.selectedText
      ? '继续追问这条线程…'
      : '就当前章节提问，例如：为什么一定要取极限？';

  return (
    <div className="ask-box">
      <div className={`selection-label${selected ? ' show' : ''}`} data-testid="selection-label">
        已选原文：<span>「{selected?.truncated ?? ''}」</span>
        <button className="clear-selection" onClick={onClear} aria-label="清除已选原文">
          ×
        </button>
      </div>
      <div className="ask-row">
        <input
          id="question"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          placeholder={placeholder}
          aria-label="提问输入框"
        />
        <button onClick={submit} disabled={asking}>
          {asking ? '思考中…' : '提问'}
        </button>
      </div>
    </div>
  );
}
