import { createContext, useContext, useEffect, useMemo, useState } from 'react';
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

  useEffect(() => {
    let cancelled = false;
    api.fetchBooks().then((list) => {
      if (cancelled) return;
      setBooks(list);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const setCurrentBookId = (id) => {
    setCurrentBookIdState(id);
    localStorage.setItem(CURRENT_BOOK_KEY, id);
  };

  const value = useMemo(() => {
    const validId = books?.some((b) => b.id === currentBookId) ? currentBookId : books?.[0]?.id ?? null;
    return { books, loading, currentBookId: validId, setCurrentBookId };
  }, [books, currentBookId]);

  return <BookContext.Provider value={value}>{children}</BookContext.Provider>;
}

export function useBooks() {
  const ctx = useContext(BookContext);
  if (!ctx) throw new Error('useBooks 必须在 BookProvider 内使用');
  return ctx;
}
