import { useState } from 'react';
import QuizPanel from './QuizPanel.jsx';
import SegmentText from './SegmentText.jsx';
import { SummaryTool, TranslateTool } from './ReaderTools.jsx';

/**
 * 右侧边栏：**阅读工具** + 学习记录。
 *
 * 上面一行是工具（AI 讲解 / 知识点大纲 / 追问 / 翻译 / 总结）——都是「读的时候顺手用一下」
 * 的动作，作用对象是读者眼前的原文；下面依次是追问线程、章末自测、我的笔记，
 * 它们是**记录与导航**，不该被工具切换藏起来，所以在下面常驻。
 *
 * 提问仍然从底部输入框发起（无论当前在哪个工具页），发出去之后自动切到「追问」页：
 * 回答落在追问页里，不切过去的话用户会以为没反应。
 */
const TABS = [
  { id: 'explain', label: 'AI 讲解' },
  { id: 'outline', label: '知识点大纲' },
  { id: 'ask', label: '追问' },
  { id: 'translate', label: '翻译' },
  { id: 'summary', label: '总结' },
];

export default function CoachPanel({
  content,
  thread,
  threads = [],
  asking,
  selected,
  progress,
  notes = [],
  quiz,
  onAsk,
  onComplete,
  onSelectThread,
  onDeleteThread,
  onOpenSource,
  onCreateNote,
  onUpdateNote,
  onDeleteNote,
  onAnswerQuiz,
  clearSelected,
  onFocusSource,
  currentPage,
  translate,
  summary,
  onTranslate,
  onSummarize,
  onCancelTool,
}) {
  const [tab, setTab] = useState('explain');

  const askAndFollow = (question) => {
    setTab('ask');
    onAsk(question);
  };

  const openThread = (id) => {
    setTab('ask');
    onSelectThread(id);
  };

  return (
    <aside className="coach">
      <div className="coach-head">
        <div className="eyebrow">本章学习助手</div>
        <h2>{content.heading}</h2>
        <MasteryPanel progress={progress} onComplete={onComplete} />
        <div className="tabs" role="tablist">
          {TABS.map((item) => (
            <button
              key={item.id}
              className={`tab${tab === item.id ? ' active' : ''}`}
              onClick={() => setTab(item.id)}
              role="tab"
              aria-selected={tab === item.id}
            >
              {item.label}
            </button>
          ))}
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
        ) : null}

        {tab === 'outline' ? (
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
        ) : null}

        {tab === 'ask' ? (
          <div className="tab-content" role="tabpanel">
            <Chat chat={thread?.messages ?? []} onOpenSource={onOpenSource} />
            {(thread?.messages ?? []).length === 0 ? (
              <p className="tool-hint">
                在原文里拖选一段再问，或者直接用下面的输入框提问；每段划词会单独成一条追问线程。
              </p>
            ) : null}
          </div>
        ) : null}

        {tab === 'translate' ? (
          <div className="tab-content" role="tabpanel">
            <TranslateTool
              selected={selected}
              currentPage={currentPage}
              state={translate}
              onRun={onTranslate}
              onCancel={onCancelTool}
            />
          </div>
        ) : null}

        {tab === 'summary' ? (
          <div className="tab-content" role="tabpanel">
            <SummaryTool
              selected={selected}
              state={summary}
              onRun={onSummarize}
              onCancel={onCancelTool}
              onOpenSource={onOpenSource}
            />
          </div>
        ) : null}

        <ThreadList threads={threads} activeId={thread?.id} onSelect={openThread} onDelete={onDeleteThread} />
        <QuizPanel quiz={quiz} onAnswer={onAnswerQuiz} />
        <NotesList
          notes={notes}
          onFocus={onFocusSource}
          onUpdate={onUpdateNote}
          onDelete={onDeleteNote}
        />
      </div>
      <AskBox
        selected={selected}
        thread={thread}
        asking={asking}
        onAsk={askAndFollow}
        onCreateNote={onCreateNote}
        onClear={clearSelected}
      />
    </aside>
  );
}

/**
 * 本章笔记：点一条回到它对应的原文，可改可删。
 *
 * 笔记与追问线程分开列：一个是「我问过什么」，一个是「我记下了什么」，
 * 混在一张列表里，用户得逐条读才知道哪条是哪个。
 */
export function NotesList({ notes = [], onFocus, onUpdate, onDelete }) {
  const [editingId, setEditingId] = useState(null);
  const [draft, setDraft] = useState('');

  if (notes.length === 0) return null;

  const startEdit = (note) => {
    setEditingId(note.id);
    setDraft(note.body);
  };

  const save = async (noteId) => {
    const text = draft.trim();
    if (!text) return;
    await onUpdate?.(noteId, text);
    setEditingId(null);
  };

  return (
    <div className="note-list" data-testid="note-list">
      <div className="thread-list-head">
        <span>我的笔记</span>
        <span>{notes.length} 条</span>
      </div>
      <ul>
        {notes.map((note) => (
          <li key={note.id} className="note-item">
            {editingId === note.id ? (
              <div className="note-edit">
                <textarea
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  aria-label="编辑笔记内容"
                />
                <div className="note-edit-actions">
                  <button type="button" onClick={() => save(note.id)}>
                    保存
                  </button>
                  <button type="button" className="ghost" onClick={() => setEditingId(null)}>
                    取消
                  </button>
                </div>
              </div>
            ) : (
              <>
                <button
                  type="button"
                  className="note-open"
                  data-testid={`note-${note.id}`}
                  onClick={() => onFocus?.(note.anchorId, '已定位到这条笔记对应的原文')}
                >
                  {note.quotedText ? (
                    <span className="note-quote">「{note.quotedText}」</span>
                  ) : (
                    <span className="note-quote">本章笔记</span>
                  )}
                  <span className="note-body">{note.body}</span>
                </button>
                <span className="note-actions">
                  <button
                    type="button"
                    onClick={() => startEdit(note)}
                    aria-label={`编辑笔记 ${note.body}`}
                  >
                    ✎
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete?.(note.id)}
                    aria-label={`删除笔记 ${note.body}`}
                  >
                    ×
                  </button>
                </span>
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
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
            {msg.noEvidence && !msg.streaming ? (
              <NoEvidenceExit message={msg} onOpenSource={onOpenSource} />
            ) : (
              <>
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
              </>
            )}
          </div>
        ),
      )}
    </div>
  );
}

/**
 * 拒答的出口：告诉用户下一步怎么办，并把教材里最接近的段落摆出来。
 *
 * 这些段落**不是回答依据**（后端放在 `closest` 而不是 `sources` 里），所以措辞上要
 * 说清「供你判断」——把没被采信过的原文说成依据，等于毁掉溯源可信度。
 */
export function NoEvidenceExit({ message, onOpenSource }) {
  const closest = message.closest ?? [];
  return (
    <div className="no-evidence" data-testid="no-evidence">
      {message.hint && <small className="no-evidence-hint">{message.hint}</small>}
      {closest.length > 0 && (
        <div className="closest-list" data-testid="closest-list">
          <small className="closest-title">教材里最接近的段落（供你判断，不是回答依据）：</small>
          {closest.map((detail) => (
            <button
              key={detail.id}
              className={`source-chip${detail.crossChapter ? ' cross' : ''}`}
              onClick={() => onOpenSource(detail.id, detail)}
            >
              {closestLabel(detail)} ↗
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function closestLabel(detail) {
  const chapter = detail.crossChapter && detail.chapterTitle ? `${detail.chapterTitle} · ` : '';
  return detail.page ? `${chapter}第 ${detail.page} 页` : detail.id;
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

/**
 * 提问框：显示已选中原文，支持回车提问；选中原文时还能直接记一条笔记。
 *
 * 「记笔记」放在这里而不是别处：这一行本来就写着「已选原文：…」，
 * 用户此刻正看着自己选中的那段话，记笔记的念头也正是在这一刻出现的。
 */
export function AskBox({ selected, thread, asking, onAsk, onCreateNote, onClear }) {
  const [value, setValue] = useState('');
  const [noteOpen, setNoteOpen] = useState(false);
  const [noteDraft, setNoteDraft] = useState('');
  const [saving, setSaving] = useState(false);

  const submit = () => {
    const q = value.trim();
    if (!q || asking) return;
    onAsk(q);
    setValue('');
  };

  const quote = selected?.text ?? '';
  const closeNote = () => {
    setNoteOpen(false);
    setNoteDraft('');
  };

  const saveNote = async () => {
    const body = noteDraft.trim();
    if (!body || saving) return;
    setSaving(true);
    const ok = await onCreateNote?.({
      anchorId: selected?.anchorId ?? '',
      quotedText: quote,
      body,
    });
    setSaving(false);
    if (ok !== false) closeNote();
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
        {/* 有选中原文时才出现：没有引用对象的笔记，位置就丢了 */}
        {selected && !noteOpen && (
          <button
            className="note-start"
            type="button"
            data-testid="note-start"
            onClick={() => setNoteOpen(true)}
          >
            记笔记
          </button>
        )}
        <button className="clear-selection" onClick={onClear} aria-label="清除已选原文">
          ×
        </button>
      </div>
      {noteOpen ? (
        <div className="note-compose" data-testid="note-compose">
          <textarea
            autoFocus
            value={noteDraft}
            onChange={(event) => setNoteDraft(event.target.value)}
            placeholder="为这段原文记一条笔记…"
            aria-label="笔记内容"
          />
          <div className="note-edit-actions">
            <button type="button" onClick={saveNote} disabled={saving || !noteDraft.trim()}>
              {saving ? '保存中…' : '保存笔记'}
            </button>
            <button type="button" className="ghost" onClick={closeNote}>
              取消
            </button>
          </div>
        </div>
      ) : (
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
      )}
    </div>
  );
}
