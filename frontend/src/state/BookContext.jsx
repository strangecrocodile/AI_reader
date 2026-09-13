import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api } from '../services/api.js';

const CURRENT_BOOK_KEY = 'ai_reader.currentBookId';
const BookContext = createContext(null);

/**
 * 全局教材状态：加载教材列表、维护「当前教材」并持久化到 localStorage。
 * 加载失败时保留错误对象，页面据此给出「连不上后端 + 重试」，而不是一直转圈。
 */
export function BookProvider({ children }) {
  const [books, setBooks] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [currentBookId, setCurrentBookIdState] = useState(() => localStorage.getItem(CURRENT_BOOK_KEY));

  const refreshBooks = useCallback(async () => {
    try {
      const list = await api.fetchBooks();
      setBooks(Array.isArray(list) ? list : []);
      setError(null);
      return list;
    } catch (err) {
      setError(err);
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  /** 失败后重试（页面上的「重试」按钮）。 */
  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    return refreshBooks().catch(() => {});
  }, [refreshBooks]);

  useEffect(() => {
    let cancelled = false;
    reload().then(() => {
      if (cancelled) return;
    });
    return () => {
      cancelled = true;
    };
  }, [reload]);

  const setCurrentBookId = (id) => {
    setCurrentBookIdState(id);
    localStorage.setItem(CURRENT_BOOK_KEY, id);
  };

  const value = useMemo(() => {
    const validId = books?.some((b) => b.id === currentBookId) ? currentBookId : books?.[0]?.id ?? null;
    return {
      books,
      loading,
      error,
      reload,
      currentBookId: validId,
      setCurrentBookId,
      refreshBooks,
    };
  }, [books, currentBookId, loading, error, reload, refreshBooks]);

  return <BookContext.Provider value={value}>{children}</BookContext.Provider>;
}

export function useBooks() {
  const ctx = useContext(BookContext);
  if (!ctx) throw new Error('useBooks 必须在 BookProvider 内使用');
  return ctx;
}
