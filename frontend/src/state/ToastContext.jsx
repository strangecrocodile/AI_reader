import { createContext, useCallback, useContext, useRef, useState } from 'react';

const ToastContext = createContext(null);

/** 轻量全局提示：useToast() 返回 toast(message) 函数。 */
export function ToastProvider({ children }) {
  const [msg, setMsg] = useState(null);
  const timer = useRef(null);

  const toast = useCallback((message) => {
    setMsg(message);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setMsg(null), 2300);
  }, []);

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div className={`notice${msg ? ' show' : ''}`} role="status">
        {msg}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast 必须在 ToastProvider 内使用');
  return ctx;
}
