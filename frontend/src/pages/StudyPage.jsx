import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import Reader, { PAGE_MODE, SCROLL_MODE } from '../components/Reader.jsx';
import CoachPanel from '../components/CoachPanel.jsx';
import SelectionBubble from '../components/SelectionBubble.jsx';
import StateCard from '../components/StateCard.jsx';
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
  const [loadError, setLoadError] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [selected, setSelected] = useState(null);
  const [threads, setThreads] = useState([]);
  const [notes, setNotes] = useState([]);
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
    setLoadError(null);
    setSelected(null);
    setProgress(null);
    setThreads([]);
    setNotes([]);
    setActiveThreadId(null);
    setBubbleOpen(false);

    // `fetchStudyContent` 对 404 返回 null（这一章确实没有内容），其余错误往上抛
    // （加载失败，可重试）。两者在界面上是完全不同的两件事，不能混成一种。
    (async () => {
      let data = null;
      try {
        data = await api.fetchStudyContent(bookId, chapterId);
      } catch (error) {
        if (!cancelled) {
          setLoadError(error);
          setLoading(false);
        }
        return;
      }
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
      api
        .fetchNotes(bookId, chapterId)
        .then((list) => {
          if (!cancelled && Array.isArray(list)) setNotes(list);
        })
        .catch(() => {});
    })();

    return () => {
      cancelled = true;
    };
  }, [bookId, chapterId, report, reloadKey]);

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
      // Range 留着，好让划词气泡在滚动后重新量一次位置（视口坐标会作废）
      range: meta.range ?? null,
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
      // 跨章与否**以 chapterId 为准**，不只看 `crossChapter` 标记：从追问线程载入的
      // 历史消息没经过 `withChapterFlags`，只凭标记会漏判，于是点跨章依据会在本章里
      // 找不到锚点、静默失败。标记仍用于文案（见 `withChapterFlags`）。
      const crossChapter = Boolean(detail?.chapterId && detail.chapterId !== chapterId);
      if (crossChapter) {
        toast(`已跳到《${detail.chapterTitle}》核对原文`);
        navigate(`/study/${bookId}/${detail.chapterId}?sourceId=${encodeURIComponent(sourceId)}`);
        return;
      }
      focusSource(sourceId, detail?.page ? `教材依据 · 第 ${detail.page} 页` : undefined);
    },
    [bookId, chapterId, focusSource, navigate, toast],
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
                // 拒答不是死路：把「下一步」和「教材里最接近的段落」也带进消息，
                // 否则用户只看到一句「没找到」，无从判断该换个问法还是问偏了。
                noEvidence: payload.noEvidence === true,
                closest: withChapterFlags(payload.closest),
                hint: payload.hint ?? '',
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

  // ---------- 笔记 ----------

  /**
   * 记一条笔记。返回 false 表示没存上——`AskBox` 据此决定要不要清空草稿：
   * 存失败还把用户刚写的东西清掉，是最气人的那种失败。
   */
  const handleCreateNote = useCallback(
    async ({ anchorId, quotedText, body }) => {
      try {
        const created = await api.createNote({ bookId, chapterId, anchorId, quotedText, body });
        setNotes((prev) => [created, ...prev]);
        // 记完顺手清掉选中：用户已经把它变成笔记了，再挂着选中状态只会让人以为没成功
        setSelected(null);
        toast('已记下这条笔记');
        return true;
      } catch (error) {
        toast(error.message || '笔记没能保存，请稍后重试');
        return false;
      }
    },
    [bookId, chapterId, toast],
  );

  const handleUpdateNote = useCallback(
    async (noteId, body) => {
      try {
        const updated = await api.updateNote(noteId, body);
        setNotes((prev) => prev.map((note) => (note.id === noteId ? updated : note)));
        toast('笔记已更新');
        return true;
      } catch (error) {
        toast(error.message || '笔记更新失败，请稍后重试');
        return false;
      }
    },
    [toast],
  );

  const handleDeleteNote = useCallback(
    async (noteId) => {
      try {
        await api.deleteNote(noteId);
      } catch {
        toast('笔记删除失败，请稍后重试');
        return;
      }
      setNotes((prev) => prev.filter((note) => note.id !== noteId));
    },
    [toast],
  );

  /** 哪些段落已经记过笔记——阅读区据此在段旁点一个记号。 */
  const notedAnchorIds = useMemo(
    () => new Set(notes.map((note) => note.anchorId).filter(Boolean)),
    [notes],
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

  if (loadError) {
    return (
      <section className="page study">
        <StateCard
          title="本章内容没能加载出来"
          description="后端没有响应，或者返回了错误。这多半是暂时的——重试一次通常就好。"
          hint={`错误信息：${loadError.message || loadError}`}
          actionLabel="重试"
          onAction={() => setReloadKey((key) => key + 1)}
        />
      </section>
    );
  }

  if (!content) {
    return (
      <section className="page study placeholder-page">
        <div className="placeholder-card">
          <h2>本章内容尚未准备</h2>
          <p>
            教材里这一章没有被解析出正文段落，或者它已经不在了。
            回学习计划换一章，或者重新导入一次教材。
          </p>
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
          bookId={bookId}
          focusId={focusId}
          onSelect={handleSelect}
          onRead={handleRead}
          chapters={chapters}
          currentChapterId={chapterId}
          onSelectChapter={handleSelectChapter}
          onOpenSource={handleOpenSource}
          notedAnchorIds={notedAnchorIds}
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
          notes={notes}
          onAsk={handleAsk}
          onComplete={handleComplete}
          onSelectThread={handleSelectThread}
          onDeleteThread={handleDeleteThread}
          onOpenSource={handleOpenSource}
          onCreateNote={handleCreateNote}
          onUpdateNote={handleUpdateNote}
          onDeleteNote={handleDeleteNote}
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
