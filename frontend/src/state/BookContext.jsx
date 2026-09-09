import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api } from '../services/api.js';

const CURRENT_BOOK_KEY = 'ai_reader.currentBookId';
const BookContext = createContext(null);

/**
 * 全局教材状态：加载教材列表、维护「当前教材」并持久化到 localStorage。
 */
export function BookProvider({ children }) {
  const [books, setBooks] = useState(null);
  const [loading, setLoading] = useState(true);
  const [currentBookId, setCurrentBookIdState] = useState(() => localStorage.getItem(CURRENT_BOOK_KEY));

  const refreshBooks = useCallback(async () => {
    const list = await api.fetchBooks();
    setBooks(list);
    setLoading(false);
    return list;
  }, []);

  useEffect(() => {
    let cancelled = false;
    refreshBooks().then(() => {
      if (cancelled) return;
    }).catch(() => {
      if (!cancelled) setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [refreshBooks]);

  const setCurrentBookId = (id) => {
    setCurrentBookIdState(id);
    localStorage.setItem(CURRENT_BOOK_KEY, id);
  };

  const value = useMemo(() => {
    const validId = books?.some((b) => b.id === currentBookId) ? currentBookId : books?.[0]?.id ?? null;
    return { books, loading, currentBookId: validId, setCurrentBookId, refreshBooks };
  }, [books, currentBookId, loading, refreshBooks]);

  return <BookContext.Provider value={value}>{children}</BookContext.Provider>;
}

export function useBooks() {
  const ctx = useContext(BookContext);
  if (!ctx) throw new Error('useBooks 必须在 BookProvider 内使用');
  return ctx;
}
