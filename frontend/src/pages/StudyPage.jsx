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
  const [progress, setProgress] = useState(null);
  const [focusId, setFocusId] = useState(null);
  const clearTimer = useRef(null);

  /**
   * 上报学习事件（进入章节 / 读到段落 / 提问 / 标记学完）。
   * 掌握度由后端按事件算出并返回拆分说明；上报失败不打断学习。
   */
  const report = useCallback(
    async (payload) => {
      try {
        const result = await api.recordLearningEvent({ bookId, chapterId, ...payload });
        if (result) setProgress(result);
        return result;
      } catch {
        return null;
      }
    },
    [bookId, chapterId],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setChat([]);
    setSelected(null);
    setProgress(null);
    api.fetchStudyContent(bookId, chapterId).then((data) => {
      if (cancelled) return;
      setContent(data);
      setLoading(false);
      if (data) report({ kind: 'open' });
    });
    return () => {
      cancelled = true;
    };
  }, [bookId, chapterId, report]);

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

  /** 读到过的段落上报（Reader 的可见性观察结果）。 */
  const handleRead = useCallback(
    (anchorIds) => {
      report({ kind: 'read', anchorIds });
    },
    [report],
  );

  const handleComplete = useCallback(async () => {
    const result = await report({ kind: 'complete' });
    toast(result ? '已标记本章学完' : '本章标记未同步，请稍后重试');
  }, [report, toast]);

  /** 更新最后一条 AI 回答（流式追加 / 收尾）。 */
  const patchLastAnswer = useCallback((patch) => {
    setChat((prev) => {
      const next = [...prev];
      for (let i = next.length - 1; i >= 0; i -= 1) {
        if (next[i].role === 'assistant') {
          next[i] = typeof patch === 'function' ? patch(next[i]) : { ...next[i], ...patch };
          break;
        }
      }
      return next;
    });
  }, []);

  /** 标注哪条依据来自其他章节（用于提示与跳转）。 */
  const withChapterFlags = useCallback(
    (details = []) =>
      details.map((detail) => ({
        ...detail,
        crossChapter: Boolean(detail.chapterId && detail.chapterId !== chapterId),
      })),
    [chapterId],
  );

  /** 点击「教材依据」：同章定位高亮，跨章跳到对应章节再定位。 */
  const handleOpenSource = useCallback(
    (sourceId, detail) => {
      if (detail?.crossChapter && detail.chapterId) {
        toast(`已跳到《${detail.chapterTitle}》核对原文`);
        navigate(`/study/${bookId}/${detail.chapterId}?sourceId=${encodeURIComponent(sourceId)}`);
        return;
      }
      focusSource(sourceId, detail?.page ? `教材依据 · 第 ${detail.page} 页` : undefined);
    },
    [bookId, focusSource, navigate, toast],
  );

  const handleAsk = useCallback(
    async (question) => {
      const ctx = selected ? '（针对你选中的原文）' : undefined;
      setChat((prev) => [
        ...prev,
        { role: 'user', text: question, context: ctx },
        { role: 'assistant', text: '', streaming: true, sources: [], sourceDetails: [] },
      ]);
      setAsking(true);
      try {
        await api.askStream(
          { question, selectedText: selected?.text, bookId, chapterId },
          {
            onDelta: (chunk) => patchLastAnswer((msg) => ({ ...msg, text: msg.text + chunk })),
            onDone: (payload) =>
              patchLastAnswer((msg) => ({
                ...msg,
                streaming: false,
                text: payload.answer ?? msg.text,
                sources: payload.sources ?? [],
                sourceDetails: withChapterFlags(payload.sourceDetails),
                scope: payload.scope,
              })),
          },
        );
      } catch {
        patchLastAnswer((msg) => ({
          ...msg,
          streaming: false,
          failed: true,
          text: msg.text || '回答失败，请稍后重试',
        }));
      }
      const updated = await report({ kind: 'ask', question });
      if (!updated) {
        toast('回答已完成，但学习进度暂时未同步');
      }
      setAsking(false);
      setSelected(null);
    },
    [selected, bookId, chapterId, patchLastAnswer, withChapterFlags, report, toast],
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
        <Reader content={content} focusId={focusId} onSelect={handleSelect} onRead={handleRead} />
        <CoachPanel
          content={content}
          chat={chat}
          asking={asking}
          selected={selected}
          progress={progress}
          onAsk={handleAsk}
          onComplete={handleComplete}
          onOpenSource={handleOpenSource}
          clearSelected={clearSelected}
          onFocusSource={focusSource}
        />
      </div>
    </section>
  );
}
