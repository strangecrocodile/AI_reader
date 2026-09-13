import React from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App.jsx';
import ErrorBoundary from './components/ErrorBoundary.jsx';
import { BookProvider } from './state/BookContext.jsx';
import { ToastProvider } from './state/ToastContext.jsx';
import './styles/global.css';
import './styles/home.css';
import './styles/study.css';
import './styles/knowledge.css';

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <ErrorBoundary>
        <BookProvider>
          <ToastProvider>
            <App />
          </ToastProvider>
        </BookProvider>
      </ErrorBoundary>
    </BrowserRouter>
  </React.StrictMode>,
);
