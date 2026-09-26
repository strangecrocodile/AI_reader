import { useCallback, useEffect, useState } from 'react';
import { api } from '../services/api.js';

/**
 * 全书搜索：输入即搜，结果点一下跳到对应章节并高亮那段原文。
 *
 * 定位和提问是两件事——用户心里已经有目标时（「我记得书里讲过梯度消失」），
 * 他需要的是「在哪一页」，而不是一段 AI 总结。此前只能去右栏当问题提，再从回答的
 * 依据里倒推位置。
 *
 * 跳转复用问答「教材依据」那条已经跑通的逻辑（`onOpenSource`）：同章定位高亮，
 * 跨章先跳章再定位，所以这里不自己写导航。
 */

/** 输入停顿多久才发请求。太短会在打字过程中打出好几次请求，太长又显得迟钝。 */
const DEBOUNCE_MS = 250;

export default function ChapterSearch({ bookId, currentChapterId, onOpenSource }) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState('');
  const [hits, setHits] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => {
      if (event.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open]);

  useEffect(() => {
    const text = value.trim();
    // 关掉搜索框或清空输入：把上一次的结果与状态一起收干净，下次打开是新的
    if (!open || !text) {
      setHits([]);
      setSearched(false);
      setLoading(false);
      setFailed(false);
      return undefined;
    }

    let cancelled = false;
    setLoading(true);
    setFailed(false);
    const timer = setTimeout(async () => {
      try {
        const result = await api.searchBook(bookId, text);
        if (cancelled) return;
        setHits(result?.hits ?? []);
        setSearched(true);
        setLoading(false);
      } catch {
        if (cancelled) return;
        // 搜索失败既不能把整页搞崩，也不能伪装成「没有结果」——两者给用户的话不一样
        setHits([]);
        setSearched(false);
        setLoading(false);
        setFailed(true);
      }
    }, DEBOUNCE_MS);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [bookId, value, open]);

  const go = useCallback(
    (hit) => {
      setOpen(false);
      onOpenSource?.(hit.anchorId, {
        chapterId: hit.chapterId,
        chapterTitle: hit.chapterTitle,
        page: hit.page,
      });
    },
    [onOpenSource],
  );

  if (!open) {
    return (
      <button
        type="button"
        className="nav-btn search-toggle"
        data-testid="search-toggle"
        onClick={() => setOpen(true)}
      >
        搜索全书
      </button>
    );
  }

  return (
    <div className="book-search" data-testid="book-search">
      <div className="book-search-row">
        <input
          autoFocus
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="在整本教材里查找…"
          aria-label="搜索整本教材"
        />
        <button type="button" className="search-close" onClick={() => setOpen(false)} aria-label="关闭搜索">
          ×
        </button>
      </div>
      {value.trim() && (
        <div className="book-search-results" data-testid="search-results">
          {loading && <p className="search-note">正在查找…</p>}
          {!loading && failed && <p className="search-note">搜索没成功，请稍后再试。</p>}
          {!loading && !failed && searched && hits.length === 0 && (
            <p className="search-note">教材里没有找到「{value.trim()}」。</p>
          )}
          {!loading &&
            !failed &&
            hits.map((hit) => (
              <button
                key={hit.anchorId}
                type="button"
                className={`search-hit${hit.chapterId !== currentChapterId ? ' cross' : ''}`}
                data-testid={`search-hit-${hit.anchorId}`}
                onClick={() => go(hit)}
              >
                <span className="search-hit-meta">
                  {hit.chapterTitle}
                  {hit.page ? ` · 第 ${hit.page} 页` : ''}
                  {hit.chapterId !== currentChapterId ? ' · 其他章节' : ''}
                </span>
                <span className="search-hit-text">{hit.text}</span>
              </button>
            ))}
        </div>
      )}
    </div>
  );
}
