import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../services/api.js';
import { useBooks } from '../state/BookContext.jsx';

const METHOD_LABELS = {
  llm: 'LLM 抽取',
  rule: '规则抽取',
  demo: '演示数据',
};

function nodePosition(index, total) {
  const columns = Math.min(3, Math.max(1, Math.ceil(Math.sqrt(total))));
  const rows = Math.ceil(total / columns);
  const column = index % columns;
  const row = Math.floor(index / columns);
  return {
    left: `${((column + 0.5) / columns) * 100}%`,
    top: `${((row + 0.5) / rows) * 100}%`,
  };
}

function methodLabel(methods) {
  if (!methods?.length) return '';
  return methods.map((method) => METHOD_LABELS[method] ?? method).join(' · ');
}

export default function KnowledgePage() {
  const { books, currentBookId } = useBooks();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [error, setError] = useState(false);
  const [selectedId, setSelectedId] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(false);
    if (!currentBookId) return undefined;
    api
      .fetchKnowledge(currentBookId)
      .then((result) => {
        if (cancelled) return;
        if (!result) {
          setError(true);
          return;
        }
        setData(result);
        setSelectedId(result.concepts?.[0]?.id ?? null);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [currentBookId]);

  const selected = useMemo(
    () => data?.concepts?.find((concept) => concept.id === selectedId) ?? data?.concepts?.[0],
    [data, selectedId],
  );

  const conceptByTitle = useMemo(
    () => new Map((data?.concepts ?? []).map((concept) => [concept.title, concept])),
    [data],
  );

  if (error) {
    return (
      <section className="page active knowledge-page">
        <div className="placeholder-card">
          <h2>知识地图暂时不可用</h2>
          <p>知识点整理没有完成，请稍后重试。</p>
          <button className="back-home" onClick={() => window.location.reload()}>
            重新加载
          </button>
        </div>
      </section>
    );
  }

  if (!books || !data) {
    return (
      <section className="page active knowledge-page" aria-busy="true">
        <p className="loading-note">正在整理知识地图…</p>
      </section>
    );
  }

  const unresolved = data.unresolved ?? [];

  return (
    <section className="page active knowledge-page">
      <header className="knowledge-header">
        <div>
          <div className="eyebrow">
            KNOWLEDGE MAP · {data.bookTitle}
            {methodLabel(data.methods) ? ` · ${methodLabel(data.methods)}` : ''}
          </div>
          <h1>把读过的内容，连成一张地图。</h1>
          <p className="sub">
            知识点来自章节讲义，并保留教材原文锚点。实线箭头是知识点之间的前置依赖，
            虚线是同一章的学习顺序；点击节点查看详情，再回到对应章节继续学习。
          </p>
        </div>
        <Link className="knowledge-back" to="/">
          返回学习计划
        </Link>
      </header>

      <div className="knowledge-stats" aria-label="知识统计">
        <Stat value={data.stats.conceptCount} label="知识点" />
        <Stat value={data.stats.learnedCount} label="已建立学习记录" />
        <Stat value={data.stats.relationCount} label="关系" />
        <Stat value={data.stats.prerequisiteCount ?? 0} label="其中前置依赖" />
        <Stat value={data.stats.unresolvedCount ?? 0} label="教材外前置" />
      </div>

      <div className="knowledge-layout">
        <section className="concept-panel" aria-label="知识点卡片">
          <div className="section-title">
            <h2>知识点卡片</h2>
            <span>{data.concepts.length} 个</span>
          </div>
          <div className="concept-list">
            {data.concepts.map((concept) => (
              <button
                key={concept.id}
                className={`concept-card${selected?.id === concept.id ? ' selected' : ''}`}
                onClick={() => setSelectedId(concept.id)}
              >
                <span className={`concept-status ${concept.status}`}>
                  {concept.status === 'learned' ? '已掌握' : concept.status === 'learning' ? '学习中' : '待学习'}
                </span>
                <strong>{concept.title}</strong>
                <span className="concept-chapter">{concept.chapterTitle}</span>
                <span className="mastery-track">
                  <i style={{ width: `${concept.mastery}%` }} />
                </span>
              </button>
            ))}
          </div>
        </section>

        <section className="graph-panel" aria-label="知识点关系图谱">
          <div className="section-title">
            <h2>关系图谱</h2>
            <span>前置依赖 · 学习顺序</span>
          </div>
          <div className="knowledge-graph" data-testid="knowledge-graph">
            <svg
              className="graph-lines"
              viewBox="0 0 100 100"
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              <defs>
                <marker
                  id="graph-arrow"
                  viewBox="0 0 10 10"
                  refX="9"
                  refY="5"
                  markerWidth="5"
                  markerHeight="5"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 0 L 10 5 L 0 10 z" />
                </marker>
              </defs>
              {data.relations.map((relation) => {
                const fromIndex = data.concepts.findIndex((concept) => concept.id === relation.source);
                const toIndex = data.concepts.findIndex((concept) => concept.id === relation.target);
                if (fromIndex < 0 || toIndex < 0) return null;
                const from = nodePosition(fromIndex, data.concepts.length);
                const to = nodePosition(toIndex, data.concepts.length);
                const isPrerequisite = relation.type === 'prerequisite';
                return (
                  <line
                    key={relation.id}
                    className={`graph-line ${isPrerequisite ? 'prerequisite' : 'sequence'}`}
                    x1={Number.parseFloat(from.left)}
                    y1={Number.parseFloat(from.top)}
                    x2={Number.parseFloat(to.left)}
                    y2={Number.parseFloat(to.top)}
                    markerEnd={isPrerequisite ? 'url(#graph-arrow)' : undefined}
                  />
                );
              })}
            </svg>
            {data.concepts.map((concept, index) => {
              const position = nodePosition(index, data.concepts.length);
              return (
                <button
                  key={concept.id}
                  className={`graph-node ${concept.status}${selected?.id === concept.id ? ' selected' : ''}`}
                  style={position}
                  onClick={() => setSelectedId(concept.id)}
                >
                  <span>{concept.title}</span>
                </button>
              );
            })}
            {data.concepts.length === 0 && <p className="graph-empty">完成一个章节后，这里会出现你的知识关系。</p>}
          </div>

          <div className="graph-legend">
            <span className="legend-item">
              <i className="legend-line prerequisite" aria-hidden="true" />
              前置依赖
            </span>
            <span className="legend-item">
              <i className="legend-line sequence" aria-hidden="true" />
              学习顺序
            </span>
          </div>

          {unresolved.length > 0 && (
            <div className="graph-external" data-testid="knowledge-external">
              <strong>教材中未出现的前置概念</strong>
              <ul>
                {unresolved.map((item) => (
                  <li key={item.name}>
                    <span className="external-name">{item.name}</span>
                    <span className="external-note">{item.requiredBy.join('、')} 依赖它</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>

        <aside className="concept-detail">
          <div className="eyebrow">SELECTED CONCEPT</div>
          {selected ? (
            <>
              <h2>{selected.title}</h2>
              <p>{selected.summary}</p>
              <div className="detail-meta">
                <span>{selected.chapterTitle}</span>
                <span>{selected.mastery}% 掌握度</span>
              </div>
              {selected.prerequisites?.length > 0 && (
                <div className="detail-prereq">
                  <span className="detail-label">前置概念</span>
                  <div className="prereq-chips">
                    {selected.prerequisites.map((name) => {
                      const target = conceptByTitle.get(name);
                      return target ? (
                        <button key={name} className="prereq-chip" onClick={() => setSelectedId(target.id)}>
                          {name}
                        </button>
                      ) : (
                        <span key={name} className="prereq-chip external" title="教材中未找到该前置概念">
                          {name}（教材外）
                        </span>
                      );
                    })}
                  </div>
                </div>
              )}
              {selected.sourceId ? (
                <button
                  className="detail-action"
                  onClick={() =>
                    navigate(
                      `/study/${data.bookId}/${selected.chapterId}?sourceId=${encodeURIComponent(selected.sourceId)}`,
                    )
                  }
                >
                  回到教材原文　↗
                </button>
              ) : (
                <span className="detail-muted">这个知识点暂时没有可定位的原文。</span>
              )}
            </>
          ) : (
            <p className="detail-muted">选择一个知识点查看详情。</p>
          )}
        </aside>
      </div>
    </section>
  );
}

function Stat({ value, label }) {
  return (
    <div className="knowledge-stat">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}
