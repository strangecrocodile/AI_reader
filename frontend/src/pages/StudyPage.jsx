import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import Reader, { PAGE_MODE, SCROLL_MODE } from '../components/Reader.jsx';
import CoachPanel from '../components/CoachPanel.jsx';
import SelectionBubble from '../components/SelectionBubble.jsx';
import { api } from '../services/api.js';
import { truncate } from '../utils/text.js';
import { useBooks } from '../state/BookContext.jsx';
import { useToast } from '../state/ToastContext.jsx';

/** 阅读方式记在本地：换章、重开页面都保持用户选的那一种。 */
const VIEW_MODE_KEY = 'ai_reader.viewMode';

function readViewMode() {
  try {
    return localStorage.getItem(VIEW_MODE_KEY) === PAGE_MODE ? PAGE_MODE : SCROLL_MODE;
  } catch {
    return SCROLL_MODE; // 隐私模式下 localStorage 可能不可用
  }
}

/** 本地消息 id（后端持久化用自己的 id，这里只用于 React key 与流式定位）。 */
let messageSeq = 0;
function nextMessageId(role) {
  messageSeq += 1;
  return `${role}-m${messageSeq}`;
}

const TITLE_CHARS = 24;

/** 无选中原文的线程：标题取第一个问题（与后端 services/threads.py 的规则一致）。 */
function threadTitleFrom(thread, question) {
  if (thread.selectedText) return thread.title;
  if ((thread.messages ?? []).some((message) => message.role === 'user')) return thread.title;
  const text = String(question || '').trim().replace(/\s+/g, ' ');
  return text.length <= TITLE_CHARS ? text : `${text.slice(0, TITLE_CHARS)}…`;
}

/** 学习页：左栏教材原文 + 右栏 AI 讲解，划词可就该段原文开一条追问线程。 */
export default function StudyPage() {
  const { bookId, chapterId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  // 章节列表复用主页那份（BookContext 只加载一次），不为导航额外发请求
  const { books } = useBooks();
  const chapters = books?.find((item) => item.id === bookId)?.chapters ?? [];
  const [viewMode, setViewMode] = useState(readViewMode);

  const [content, setContent] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [threads, setThreads] = useState([]);
  const [activeThreadId, setActiveThreadId] = useState(null);
  const [bubbleOpen, setBubbleOpen] = useState(false);
  const [bubbleRect, setBubbleRect] = useState(null);
  const [asking, setAsking] = useState(false);
  const [progress, setProgress] = useState(null);
  const [focusId, setFocusId] = useState(null);
  const clearTimer = useRef(null);

  const activeThread = threads.find((thread) => thread.id === activeThreadId) ?? null;

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
    setSelected(null);
    setProgress(null);
    setThreads([]);
    setActiveThreadId(null);
    setBubbleOpen(false);
    api.fetchStudyContent(bookId, chapterId).then((data) => {
      if (cancelled) return;
      setContent(data);
      setLoading(false);
      if (!data) return;
      report({ kind: 'open' });
      api
        .fetchThreads(bookId, chapterId)
        .then((list) => {
          if (!cancelled && Array.isArray(list)) setThreads(list);
        })
        .catch(() => {});
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

  const handleSelect = useCallback((text, meta = {}) => {
    setSelected({
      text,
      truncated: truncate(text),
      anchorId: meta.anchorId ?? '',
      rect: meta.rect ?? null,
    });
    // 选中新原文时收起浮层：下一次提问会为新选区另开一条线程
    setBubbleOpen(false);
    setActiveThreadId(null);
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

  // ---------- 追问线程 ----------

  /** 打开划词气泡：没有活动线程时先建一条（绑定选中原文的锚点）。 */
  const handleOpenBubble = useCallback(async () => {
    setBubbleRect(selected?.rect ?? null);
    if (!activeThreadId) {
      try {
        const created = await api.createThread({
          bookId,
          chapterId,
          anchorId: selected?.anchorId ?? '',
          selectedText: selected?.text ?? '',
        });
        setThreads((prev) => [created, ...prev]);
        setActiveThreadId(created.id);
      } catch {
        toast('追问线程创建失败，请稍后重试');
        return;
      }
    }
    setBubbleOpen(true);
  }, [activeThreadId, bookId, chapterId, selected, toast]);

  const handleCloseBubble = useCallback(() => setBubbleOpen(false), []);

  const patchThreadMessages = useCallback((threadId, patch) => {
    setThreads((prev) =>
      prev.map((thread) =>
        thread.id === threadId ? { ...thread, messages: patch(thread.messages ?? []) } : thread,
      ),
    );
  }, []);

  /** 更新线程里最后一条 AI 回答（流式追加 / 收尾）。 */
  const patchLastAnswer = useCallback(
    (threadId, patch) => {
      patchThreadMessages(threadId, (messages) => {
        const next = [...messages];
        for (let i = next.length - 1; i >= 0; i -= 1) {
          if (next[i].role === 'assistant') {
            next[i] = typeof patch === 'function' ? patch(next[i]) : { ...next[i], ...patch };
            break;
          }
        }
        return next;
      });
    },
    [patchThreadMessages],
  );

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

  const askInThread = useCallback(
    async (threadId, question, contextText) => {
      const stamp = new Date().toISOString();
      setThreads((prev) =>
        prev.map((thread) =>
          thread.id === threadId
            ? {
                ...thread,
                updatedAt: stamp,
                title: threadTitleFrom(thread, question),
                messages: [
                  ...(thread.messages ?? []),
                  {
                    id: nextMessageId('user'),
                    role: 'user',
                    text: question,
                    context: contextText ? '（针对你选中的原文）' : undefined,
                    createdAt: stamp,
                  },
                  {
                    id: nextMessageId('assistant'),
                    role: 'assistant',
                    text: '',
                    streaming: true,
                    sources: [],
                    sourceDetails: [],
                    createdAt: stamp,
                  },
                ],
              }
            : thread,
        ),
      );

      setAsking(true);
      try {
        await api.askStream(
          { question, selectedText: contextText, bookId, chapterId, threadId },
          {
            onDelta: (chunk) =>
              patchLastAnswer(threadId, (msg) => ({ ...msg, text: msg.text + chunk })),
            onDone: (payload) =>
              patchLastAnswer(threadId, (msg) => ({
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
        patchLastAnswer(threadId, (msg) => ({
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
    },
    [bookId, chapterId, patchLastAnswer, withChapterFlags, report, toast],
  );

  /** 提问：气泡内或右栏输入框都走这里；没有活动线程时先建一条。 */
  const handleAsk = useCallback(
    async (question) => {
      const selectionForThread = selected;
      setSelected(null);
      let threadId = activeThreadId;
      if (!threadId) {
        try {
          const created = await api.createThread({
            bookId,
            chapterId,
            anchorId: selectionForThread?.anchorId ?? '',
            selectedText: selectionForThread?.text ?? '',
          });
          setThreads((prev) => [created, ...prev]);
          setActiveThreadId(created.id);
          threadId = created.id;
        } catch {
          toast('追问线程创建失败，请稍后重试');
          return;
        }
      }
      await askInThread(threadId, question, selectionForThread?.text);
    },
    [activeThreadId, askInThread, bookId, chapterId, selected, toast],
  );

  /** 切换到某条线程：定位到它绑定的原文锚点。 */
  const handleSelectThread = useCallback(
    (threadId) => {
      const thread = threads.find((item) => item.id === threadId);
      if (!thread) return;
      setActiveThreadId(threadId);
      setBubbleOpen(false);
      if (thread.anchorId) {
        focusSource(thread.anchorId, '已定位到这条追问对应的原文');
      }
    },
    [threads, focusSource],
  );

  const handleDeleteThread = useCallback(
    async (threadId) => {
      try {
        await api.deleteThread(threadId);
      } catch {
        toast('线程删除失败，请稍后重试');
        return;
      }
      setThreads((prev) => prev.filter((thread) => thread.id !== threadId));
      if (activeThreadId === threadId) setActiveThreadId(null);
    },
    [activeThreadId, toast],
  );

  /** 切换到另一章（顶部章节导航）。跨章定位原文走 handleOpenSource。 */
  const handleSelectChapter = useCallback(
    (id) => {
      if (!id || id === chapterId) return;
      navigate(`/study/${bookId}/${id}`);
    },
    [bookId, chapterId, navigate],
  );

  const handleViewModeChange = useCallback((mode) => {
    setViewMode(mode);
    try {
      localStorage.setItem(VIEW_MODE_KEY, mode);
    } catch {
      // 记不住阅读方式不影响本次阅读，忽略即可
    }
  }, []);

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
      <div className="mobile-warning">窄屏下先阅读教材原文，AI 讲解与提问区在原文下方。</div>
      <div className="study-layout">
        <Reader
          content={content}
          focusId={focusId}
          onSelect={handleSelect}
          onRead={handleRead}
          chapters={chapters}
          currentChapterId={chapterId}
          onSelectChapter={handleSelectChapter}
          viewMode={viewMode}
          onViewModeChange={handleViewModeChange}
        />
        <CoachPanel
          content={content}
          thread={activeThread}
          threads={threads}
          asking={asking}
          selected={selected}
          progress={progress}
          onAsk={handleAsk}
          onComplete={handleComplete}
          onSelectThread={handleSelectThread}
          onDeleteThread={handleDeleteThread}
          onOpenSource={handleOpenSource}
          clearSelected={clearSelected}
          onFocusSource={focusSource}
        />
      </div>
      <SelectionBubble
        selection={selected}
        anchor={bubbleRect}
        thread={activeThread}
        open={bubbleOpen}
        asking={asking}
        onOpen={handleOpenBubble}
        onClose={handleCloseBubble}
        onAsk={handleAsk}
        onOpenSource={handleOpenSource}
      />
    </section>
  );
}
