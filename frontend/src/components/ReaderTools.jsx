/**
 * 右侧边栏里的两个阅读工具：翻译与总结。
 *
 * 它们与「AI 讲解」的区别在于**作用对象由读者决定**：选中的那段原文、正在看的那一页、
 * 或者整章。所以每个工具都先让用户看清楚「这次要处理什么」，再开始生成——
 * 生成一次要等几秒到几十秒，点错了再等一次是纯粹的浪费。
 *
 * 输出都带锚点：译文逐段对齐原文段落，总结的每条依据都能点回原文核对。
 * 这是整个产品的底线——工具产出也必须能回到教材，而不是一段无处可查的文字。
 */

const LANGUAGE_LABELS = { zh: '中文', en: '英文', auto: '自动' };

/** 工具面板通用的状态行：正在生成 / 出错 / 提示。 */
function ToolStatus({ state, onCancel }) {
  if (state.error) {
    return (
      <p className="tool-error" role="alert">
        {state.error}
      </p>
    );
  }
  if (state.notice) {
    return <p className="tool-notice">{state.notice}</p>;
  }
  if (state.status === 'running') {
    return (
      <p className="tool-progress" role="status">
        {state.progress?.chunkCount > 1
          ? `正在生成…（第 ${state.progress.chunk}/${state.progress.chunkCount} 部分）`
          : '正在生成…'}
        {onCancel ? (
          <button type="button" className="ghost" onClick={onCancel}>
            停止
          </button>
        ) : null}
      </p>
    );
  }
  return null;
}

/**
 * AI 翻译。
 *
 * 范围只有两个：「选中的原文」与「本页」——一整章几百段逐段翻译既慢又贵，
 * 而且没人会一口气读完（后端也只接受这两种范围，理由见 services/tools.py）。
 * 没有选中原文时默认本页，并显示是哪一页。
 */
export function TranslateTool({ selected, currentPage, state, onRun, onCancel }) {
  const scope = state.scope ?? (selected ? 'selection' : 'page');
  const canRun = scope === 'selection' ? Boolean(selected?.text) : currentPage != null;

  return (
    <div className="tool-panel" data-testid="translate-tool">
      <div className="tool-row">
        <span className="tool-label">范围</span>
        <div className="tool-choice" role="group" aria-label="翻译范围">
          <button
            type="button"
            className={scope === 'selection' ? 'active' : ''}
            aria-pressed={scope === 'selection'}
            disabled={!selected?.text}
            title={selected?.text ? '翻译选中的这段原文' : '先在原文里选中一段文字'}
            onClick={() => onRun({ scope: 'selection', target: state.target })}
          >
            选中原文
          </button>
          <button
            type="button"
            className={scope === 'page' ? 'active' : ''}
            aria-pressed={scope === 'page'}
            disabled={currentPage == null}
            title={currentPage == null ? '还没读到某一页' : `翻译第 ${currentPage} 页的正文段落`}
            onClick={() => onRun({ scope: 'page', target: state.target })}
          >
            {currentPage == null ? '本页' : `本页（第 ${currentPage} 页）`}
          </button>
        </div>
      </div>
      <div className="tool-row">
        <span className="tool-label">译成</span>
        <div className="tool-choice" role="group" aria-label="目标语言">
          {['auto', 'zh', 'en'].map((value) => (
            <button
              key={value}
              type="button"
              className={(state.target ?? 'auto') === value ? 'active' : ''}
              aria-pressed={(state.target ?? 'auto') === value}
              onClick={() => onRun({ scope, target: value === 'auto' ? '' : value })}
            >
              {LANGUAGE_LABELS[value]}
            </button>
          ))}
        </div>
      </div>

      {!canRun && state.status !== 'running' ? (
        <p className="tool-hint">
          {scope === 'selection'
            ? '在左侧原文里拖选一段文字，就能翻译它。'
            : '翻到某一页（原版视图）或滚动到正文，就可以翻译这一页。'}
        </p>
      ) : null}

      <ToolStatus state={state} onCancel={onCancel} />

      {state.entries?.length ? (
        <div className="tool-results" data-testid="translate-results">
          {state.entries.map((entry, index) => (
            <div className="translate-pair" key={entry.anchorId || `seg-${index}`}>
              <p className="translate-source">
                {entry.page ? <span className="pair-page">第 {entry.page} 页</span> : null}
                {entry.source}
              </p>
              <p className="translate-text" data-testid="translate-text">
                {entry.text || (state.status === 'running' ? '…' : '')}
                {state.status === 'running' && entry.streaming ? (
                  <span className="stream-caret" aria-hidden="true" />
                ) : null}
              </p>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/**
 * AI 总结。
 *
 * 范围两个：整章（默认）与选中的原文。整章总结生成后由后端缓存，重开这一章直接读回，
 * 不必再等一遍，也不会因为重开一次就多花一次模型调用。
 */
export function SummaryTool({ selected, state, onRun, onCancel, onOpenSource }) {
  const scope = state.scope ?? 'chapter';
  return (
    <div className="tool-panel" data-testid="summary-tool">
      <div className="tool-row">
        <span className="tool-label">范围</span>
        <div className="tool-choice" role="group" aria-label="总结范围">
          <button
            type="button"
            className={scope === 'chapter' ? 'active' : ''}
            aria-pressed={scope === 'chapter'}
            title={state.cached ? '重新生成本章总结' : '总结本章'}
            onClick={() => onRun({ scope: 'chapter' })}
          >
            本章
          </button>
          <button
            type="button"
            className={scope === 'selection' ? 'active' : ''}
            aria-pressed={scope === 'selection'}
            disabled={!selected?.text}
            title={selected?.text ? '总结选中的这段原文' : '先在原文里选中一段文字'}
            onClick={() => onRun({ scope: 'selection' })}
          >
            选中原文
          </button>
        </div>
        {state.cached ? <span className="tool-badge">已缓存</span> : null}
      </div>

      {state.pages?.length ? (
        <p className="tool-hint">
          覆盖第 {state.pages[0]}–{state.pages[state.pages.length - 1]} 页
          {state.totalParagraphs > state.paragraphCount
            ? `（共 ${state.totalParagraphs} 段，本次纳入 ${state.paragraphCount} 段）`
            : `（${state.paragraphCount} 段）`}
        </p>
      ) : null}

      <ToolStatus state={state} onCancel={onCancel} />

      {state.summary ? (
        <div className="summary-body" data-testid="summary-body">
          {state.summary.split('\n').map((line, index) =>
            line.startsWith('- ') ? (
              <p key={index} className="summary-line">
                {line.slice(2)}
              </p>
            ) : (
              <p key={index} className="summary-overview">
                {line}
              </p>
            ),
          )}
          {state.status === 'running' ? <span className="stream-caret" aria-hidden="true" /> : null}
        </div>
      ) : state.status === 'idle' ? (
        <p className="tool-hint">还没有总结。点上面的「本章」生成一份，之后重开这一章会直接读回缓存。</p>
      ) : null}

      {state.sources?.length ? (
        <div className="answer-sources" data-testid="summary-sources">
          {state.sources.map((sid) => {
            const detail = (state.sourceDetails ?? []).find((item) => item.id === sid);
            return (
              <button
                key={sid}
                className={`source-chip${detail?.crossChapter ? ' cross' : ''}`}
                onClick={() => onOpenSource?.(sid, detail)}
              >
                {detail?.page ? `教材依据 · 第 ${detail.page} 页` : `教材依据 ${sid}`} ↖
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

/** 两个工具共用的「还没有生成过」空态（面板首次打开时用）。 */
export function toolIdleState(overrides = {}) {
  return {
    status: 'idle',
    scope: null,
    target: null,
    entries: [],
    summary: '',
    sources: [],
    sourceDetails: [],
    notice: '',
    error: '',
    cached: false,
    progress: null,
    ...overrides,
  };
}
