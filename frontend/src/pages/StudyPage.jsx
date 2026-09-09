import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import Reader from '../components/Reader.jsx';
import CoachPanel from '../components/CoachPanel.jsx';
import { api } from '../services/api.js';
import { truncate } from '../utils/text.js';
import { useToast } from '../state/ToastContext.jsx';

/** 学习页：左栏教材原文 + 右栏 AI 讲解与问答。 */
export default function StudyPage() {
  const { bookId, chapterId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();

  const [content, setContent] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [chat, setChat] = useState([]);
  const [asking, setAsking] = useState(false);
  const [focusId, setFocusId] = useState(null);
  const clearTimer = useRef(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setChat([]);
    setSelected(null);
    api.fetchStudyContent(bookId, chapterId).then((data) => {
      if (cancelled) return;
      setContent(data);
      setLoading(false);
      if (data) {
        api
          .markChapterProgress({ bookId, chapterId, status: 'learning', mastery: 15 })
          .catch(() => {});
      }
    });
    return () => {
      cancelled = true;
    };
  }, [bookId, chapterId]);

  // 锚点定位：设置 focusId，并在短暂高亮后自动清除
  const focusSource = useCallback(
    (id, label) => {
      setFocusId(id);
      clearTimeout(clearTimer.current);
      clearTimer.current = setTimeout(() => setFocusId(null), 2200);
      toast(label ?? '已定位到教材原文');
    },
    [toast],
  );

  useEffect(() => {
    const sourceId = searchParams.get('sourceId');
    if (sourceId && content) {
      focusSource(sourceId, '已定位到知识点原文');
    }
  }, [content, searchParams, focusSource]);

  const handleSelect = useCallback((text) => {
    setSelected({ text, truncated: truncate(text) });
  }, []);

  const clearSelected = useCallback(() => setSelected(null), []);

  const handleAsk = useCallback(
    async (question) => {
      const ctx = selected ? '（针对你选中的原文）' : undefined;
      setChat((prev) => [...prev, { role: 'user', text: question, context: ctx }]);
      setAsking(true);
      const res = await api.ask({ question, selectedText: selected?.text, bookId, chapterId });
      setChat((prev) => [...prev, { role: 'assistant', text: res.text, sources: res.sources }]);
      try {
        await api.markChapterProgress({ bookId, chapterId, status: 'learning', mastery: 42 });
      } catch {
        toast('回答已完成，但学习进度暂时未同步');
      }
      setAsking(false);
      setSelected(null);
    },
    [selected, bookId, chapterId, toast],
  );

  if (loading) {
    return (
      <section className="page study" aria-busy="true">
        <p className="loading-note">正在加载本章内容…</p>
      </section>
    );
  }

  if (!content) {
    return (
      <section className="page study placeholder-page">
        <div className="placeholder-card">
          <h2>本章内容尚未准备</h2>
          <p>演示数据目前只包含「高等数学 · 第二章 · 2.1 导数的概念」。后续章节接入真实 PDF 解析后即可学习。</p>
          <button className="back-home" onClick={() => navigate('/')}>
            ← 返回学习计划
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="page study">
      <div className="mobile-warning">为便于演示「原文—讲解」联动，请在桌面宽度下体验完整界面。</div>
      <div className="study-layout">
        <Reader content={content} focusId={focusId} onSelect={handleSelect} />
        <CoachPanel
          content={content}
          chat={chat}
          asking={asking}
          selected={selected}
          onAsk={handleAsk}
          clearSelected={clearSelected}
          onFocusSource={focusSource}
        />
      </div>
    </section>
  );
}
