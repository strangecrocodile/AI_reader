import { useState } from 'react';
import SegmentText from './SegmentText.jsx';

/**
 * AI 讲解侧栏：顶部 Tab（AI 讲解 / 知识点大纲）+ 讲解内容 + 问答区。
 * 顶部还展示由学习事件算出的掌握度及其构成（见 services/progress.js）。
 */
export default function CoachPanel({
  content,
  chat,
  asking,
  selected,
  progress,
  onAsk,
  onComplete,
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
        <Chat chat={chat} asking={asking} onFocusSource={onFocusSource} />
      </div>
      <AskBox selected={selected} asking={asking} onAsk={onAsk} onClear={clearSelected} />
    </aside>
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

/** 问答对话流：用户气泡 + AI 回答（含教材依据锚点）。 */
export function Chat({ chat, asking, onFocusSource }) {
  if (chat.length === 0 && !asking) return null;
  return (
    <div className="chat show" data-testid="chat" aria-live="polite">
      {chat.map((msg, i) =>
        msg.role === 'user' ? (
          <div key={i} className="bubble user-bubble">
            {msg.text}
            {msg.context && <small className="ctx-note">{msg.context}</small>}
          </div>
        ) : (
          <div key={i} className="bubble answer" data-testid="answer">
            <b>AI讲师</b>
            <br />
            {msg.text}
            {msg.sources?.length > 0 && (
              <div className="answer-sources">
                {msg.sources.map((sid) => (
                  <button
                    key={sid}
                    className="source-chip"
                    onClick={() => onFocusSource(sid)}
                  >
                    {sourceLabel(sid, msg.sourceDetails)} ↖
                  </button>
                ))}
              </div>
            )}
          </div>
        ),
      )}
      {asking && (
        <div className="bubble answer pending">
          <b>AI讲师</b>
          <br />
          正在思考…
        </div>
      )}
    </div>
  );
}

function sourceLabel(sourceId, details = []) {
  const detail = details.find((item) => item.id === sourceId);
  if (detail?.page) return `教材依据 · 第 ${detail.page} 页`;
  return `教材依据 ${sourceId.replace('source-', '#')}`;
}

/** 提问框：显示已选中原文，支持回车提问。 */
export function AskBox({ selected, asking, onAsk, onClear }) {
  const [value, setValue] = useState('');

  const submit = () => {
    const q = value.trim();
    if (!q || asking) return;
    onAsk(q);
    setValue('');
  };

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
          placeholder={selected ? '围绕这段原文提问…' : '就当前章节提问，例如：为什么一定要取极限？'}
          aria-label="提问输入框"
        />
        <button onClick={submit} disabled={asking}>
          {asking ? '思考中…' : '提问'}
        </button>
      </div>
    </div>
  );
}
