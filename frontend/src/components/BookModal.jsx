import { useEffect, useRef, useState } from 'react';
import { useBooks } from '../state/BookContext.jsx';
import { useToast } from '../state/ToastContext.jsx';
import { api, MAX_UPLOAD_BYTES } from '../services/api.js';

/** 与后端 services/ingest.py 的 SUPPORTED_MESSAGE 保持一致，前端只做前置提示。 */
const SUPPORTED_EXTENSIONS = ['.pdf', '.docx', '.txt', '.md'];
const FORMAT_HINT = '目前支持 PDF / Word(.docx) / 纯文本(.txt/.md) 教材；.doc 请先另存为 .docx';
const MAX_UPLOAD_MB = Math.round(MAX_UPLOAD_BYTES / (1024 * 1024));

/**
 * 解析受限时给的补救建议：症状在界面上，原因多半在文档本身。
 *
 * 这里**不再**提「整本是扫描图片」：扫描件现在会自动走 OCR（见后端 upload_book 的
 * 202 分支），压根到不了这条提示；真到了这里（比如部分页是图片的混合 PDF），
 * 让用户「自己转成 .md 再上传」也是多余的建议。
 */
const WARNING_TIP =
  '常见原因：正文写在表格里、文本框里，或整页是图片。把内容改为普通段落（Word 用「标题 1/2」做章节），或另存为 .md / .txt 后重新上传，识别效果最好。';

/** 扫描件识别失败时的说明。要点是「一个字都没入库」，别让用户以为能凑合看。 */
const OCR_FAIL_TIP =
  '识别到一半的教材不会入库——半本书的溯源会指向不存在的原文，比没有更糟。请重新上传；若反复失败，可以先用 .md / .txt 版本。';

/**
 * 轮询的各项时限。
 *
 * 打包成一个**可以改**的对象，纯粹是为了测试：15 分钟的卡死检测没法真等，
 * 也没法用假时钟（`userEvent` 内部要 `Date.now()` 推进，冻住就死循环）。
 * 测试在渲染前把值压到毫秒级，生产代码只读不改。
 */
export const OCR_POLL_LIMITS = {
  /** 轮询间隔。后端每识别一页就写一次库，1.5 秒足够跟手，又不至于把 SQLite 敲出火星。 */
  intervalMs: 1500,
  /**
   * 每页给多少秒预算。
   *
   * 实测：4 线程（`AI_READER_OCR_THREADS` 默认值）在 28 核机器上约 12.3 秒/页。
   * 这里给 30 秒，留 2.4 倍余量给核心更少的机器，及边跑边服务请求的情况。
   *
   * 血的教训：第一版按 3.4 秒/页估的 45 分钟总上限。那个数字来自验证脚本里
   * `RapidOCR()` 默认用满 28 核的测量——生产是 4 线程，慢了 3.6 倍。结果一本
   * 231 页的书跑了 47 分 28 秒，前端在 45 分钟放弃，**比完成早 2 分半**，
   * 教材明明入库了却始终不出现在列表里。
   */
  secondsPerPage: 30,
  /** 模型加载与头几页偏慢的固定开销。 */
  pageSlack: 30,
  /** 再小的书也至少等这么久——扫描件通常是几十页起，没必要为小书缩短。 */
  minBudgetMs: 45 * 60 * 1000,
  /**
   * 进度多久不动就认定是**卡死**而不是慢。
   *
   * 这条比「总时长」有用得多：总时长区分不了「慢」和「死」，而用户遇到的恰恰是慢。
   * 15 分钟没有任何一页完成，基本是 worker 真的挂了（或整机睡过去了）。
   */
  stallMs: 15 * 60 * 1000,
};

/** 本次识别任务的等待预算，按页数算。导出出来是为了能单测——分母算错没人会注意到。 */
export function ocrPollBudget(totalPages, limits = OCR_POLL_LIMITS) {
  const pages = Number(totalPages) || 0;
  return Math.max(limits.minBudgetMs, (pages + limits.pageSlack) * limits.secondsPerPage * 1000);
}

/**
 * 进行中的任务 id。存 localStorage 是为了**刷新页面后能接上进度**：
 * 一次识别几十分钟，用户必然会在中途刷新，只放在组件 state 里就永久丢了。
 *
 * 读写一律 try/catch：Safari 无痕模式下 localStorage 直接抛异常，为了一句进度
 * 提示把整个弹窗搞崩不值得。
 */
const OCR_TASK_KEY = 'ai_reader.ocrTaskId';

function readStoredOcrTaskId() {
  try {
    return localStorage.getItem(OCR_TASK_KEY) || null;
  } catch {
    return null;
  }
}

function rememberStoredOcrTaskId(taskId) {
  try {
    localStorage.setItem(OCR_TASK_KEY, taskId);
  } catch {
    // 存不下就只是「刷新后接不上」，这次识别照常跑
  }
}

function forgetStoredOcrTaskId() {
  try {
    localStorage.removeItem(OCR_TASK_KEY);
  } catch {
    // 同上，删不掉也不影响本次会话
  }
}

/** 更换教材弹窗：可切换已有教材，也可上传 PDF / Word / 纯文本教材。 */
export default function BookModal({ open, onClose }) {
  const { books, currentBookId, setCurrentBookId, refreshBooks } = useBooks();
  const toast = useToast();
  const inputRef = useRef(null);
  const [uploading, setUploading] = useState(false);
  const [notice, setNotice] = useState(null);
  // 初值直接从 localStorage 取：刷新页面后要能接上还没跑完的那次识别
  const [taskId, setTaskId] = useState(() => readStoredOcrTaskId());
  const [task, setTask] = useState(null);

  /**
   * 打开弹窗就重读一次教材列表。
   *
   * 这一条是「列表自愈」：列表原本只在 Provider 挂载时拉一次，之后只有上传 /
   * 识别成功才主动刷新。于是任何在后台完成的入库（最典型的就是几十分钟的 OCR）
   * 都不会体现在界面上，用户只能自己想到去刷新页面。重开弹窗就重读服务端，
   * 成本是一次请求，收益是这一类「东西明明在库里却看不见」的问题不会再出现。
   *
   * 用 `refreshBooks` 而不是 `reload`：前者不置 `loading = true`，不会让主页闪加载态。
   */
  useEffect(() => {
    if (!open) return;
    refreshBooks().catch(() => {
      // 拉不到时 BookProvider 会置 error，主页随即换成「连不上教材服务 + 重试」。
      // 这是想要的结果：连不上就该说出来，而不是让人对着一个点不动的列表继续点。
    });
  }, [open, refreshBooks]);

  /**
   * 轮询扫描件识别进度，直到 `done` / `failed` / 任务消失 / 放弃等待。
   *
   * **这个 effect 必须声明在下面那句 `if (!open) return null` 之前**：Hook 不能在
   * 渲染中途被跳过，放到早退之后，一开一合弹窗 React 就会抛错。
   * 同理它**不依赖 `open`**：识别要跑几十分钟，中途关掉弹窗是正常操作，关掉之后
   * 照样得继续问，才能在他回来时（或通过 toast）把结果告诉他。
   *
   * 依赖数组刻意只写 `[taskId]`：`task` 每 1.5 秒就是一个新对象，把 `task` 或
   * 它的 `donePages` 放进来，等于每轮都重建 effect——预算计时与卡死计时都会被
   * 反复重置，两个保险同时失效。闭包里的 `refreshBooks` / `toast` 虽然身份会变，
   * 但它们操作的都是 Provider 里的状态，用哪一次渲染的版本结果一样。
   */
  useEffect(() => {
    if (!taskId) return undefined;
    const { intervalMs, stallMs, minBudgetMs } = OCR_POLL_LIMITS;
    const startedAt = Date.now();
    // 预算按页数算，但页数要等第一次拿到任务才知道；先按最保守的下限起步，
    // 拿到 totalPages 后立刻换成真实预算。
    let budget = minBudgetMs;
    let lastDone = -1;
    let lastProgressAt = Date.now();
    let timer = null;
    let cancelled = false;

    const stop = () => {
      timer = null;
      forgetStoredOcrTaskId();
      setTaskId(null);
      setTask(null);
    };

    /** 放弃等待。**先刷一次列表再提示**——「刚好在完成前放弃」正是踩过的坑。 */
    const giveUp = async (message) => {
      stop();
      try {
        await refreshBooks();
      } catch {
        // 刷不动就算了，用户自己刷新页面也能看到
      }
      toast(message);
    };

    const tick = async () => {
      if (cancelled) return;
      if (Date.now() - lastProgressAt > stallMs) {
        await giveUp('扫描件识别卡住了（进度十几分钟没有变化），已停止等待；这本教材没有导入');
        return;
      }
      if (Date.now() - startedAt > budget) {
        await giveUp('扫描件识别耗时超出预期，已停止等待；识别可能仍在后台继续，稍后刷新页面看看');
        return;
      }

      let latest;
      try {
        latest = await api.fetchOcrTask(taskId);
      } catch {
        // 网络抖动而已，不当成失败，下一轮再问
        timer = setTimeout(tick, intervalMs);
        return;
      }
      if (cancelled) return;

      if (!latest) {
        // 404：后端重启过，跑识别的线程随进程没了。诚实说中断，别一直转圈。
        stop();
        toast('扫描件识别被服务重启打断，这本教材没有导入，请重新上传');
        return;
      }

      setTask(latest);
      if (latest.totalPages) budget = ocrPollBudget(latest.totalPages);
      if (latest.donePages !== lastDone) {
        lastDone = latest.donePages;
        lastProgressAt = Date.now();
      }

      if (latest.status === 'done') {
        stop();
        // 先刷新列表再切过去：否则 setCurrentBookId 指向一本本地列表里还没有的书，
        // 页面会短暂地显示「教材不存在」。
        try {
          await refreshBooks();
        } catch {
          // 列表没刷出来不影响已经入库的教材，下次进主页会再拉一次
        }
        if (latest.bookId) setCurrentBookId(latest.bookId);
        toast(`《${latest.title}》扫描件识别完成，已导入知识库`);
        return;
      }

      if (latest.status === 'failed') {
        stop();
        const text = latest.message || '识别过程中出错，这本教材没有导入。';
        // 弹窗可能已经被关掉了，所以 toast 和面板都给：toast 保证一定能看到，
        // 面板留在弹窗里供用户回头细看。
        toast(`《${latest.title}》识别失败：${text}`);
        setNotice({
          heading: `《${latest.title}》没能识别成功`,
          text,
          tip: OCR_FAIL_TIP,
          action: '知道了',
        });
        return;
      }

      timer = setTimeout(tick, intervalMs);
    };

    timer = setTimeout(tick, intervalMs);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [taskId, refreshBooks, setCurrentBookId, toast]);

  if (!open) return null;

  /** 关闭时清掉上一次的提示，免得再打开时挂着一条过期的警告。
   *  识别任务本身不动——它跑在后端，关窗口只是不看进度。 */
  const close = () => {
    setNotice(null);
    onClose();
  };

  const choose = (book) => {
    if (book.id !== currentBookId) {
      setCurrentBookId(book.id);
      const name = [book.title, book.edition].filter(Boolean).join(' ');
      toast(`已切换为《${name}》`);
    }
    close();
  };

  const upload = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    const name = file.name.toLowerCase();
    if (!SUPPORTED_EXTENSIONS.some((ext) => name.endsWith(ext))) {
      toast(FORMAT_HINT);
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      toast(`文件超过 ${MAX_UPLOAD_MB} MB，超过了后端能读取的上限，请拆分或压缩后再上传`);
      return;
    }
    setUploading(true);
    try {
      const result = await api.uploadBook(file);
      if (result.kind === 'ocr') {
        // 扫描件：后端已经把活儿转成异步任务了，这里只负责盯着进度。
        // 不关弹窗——进度条得让用户看得见。
        setNotice(null);
        setTask(result.task);
        rememberStoredOcrTaskId(result.task.id);
        setTaskId(result.task.id);
        return;
      }
      const uploaded = result.book;
      const list = await refreshBooks();
      const imported = list.find((book) => book.id === uploaded.id) ?? uploaded;
      setCurrentBookId(imported.id);
      // 解析受限时不自动关闭：这条提示要让用户看清并知道怎么补救，
      // 一闪而过的 toast 做不到（关掉弹窗后信息就没了）。
      if (imported.contentWarning) {
        setNotice({
          heading: `《${imported.title}》已导入，但内容可能没被完整读取`,
          text: imported.contentWarning,
          tip: WARNING_TIP,
          action: '知道了，先这样看',
        });
        return;
      }
      toast(`《${imported.title}》已上传并识别 ${imported.chapters.length} 个章节`);
      close();
    } catch (error) {
      toast(error.message || '教材上传失败');
    } finally {
      setUploading(false);
    }
  };

  /**
   * 删除一本教材。这里是全站**唯一不可逆**的操作，所以：
   *
   * 1. 用原生 `confirm()` 拦住一次。它丑，但它是**同步阻塞**的：必须选「确定」或「取消」
   *    才能继续，不会被点空白处顺手关掉，也不用自己管焦点和 Esc。确认文案必须把代价说全——
   *    删掉的不只是书名，还有章节、段落、AI 讲解、学习进度；扫描件更要再等几十分钟。
   * 2. 删成功后**必须 `refreshBooks()`**，而不是本地把这本书从数组里滤掉。后端才是
   *    真相，本地过滤在「删到一半失败」时会显示出一本其实还在的教材。
   */
  const remove = async (book) => {
    const name = [book.title, book.edition].filter(Boolean).join(' · ');
    const ok = window.confirm(
      `确定删除《${name}》吗？\n\n` +
        `它的 ${book.chapters.length} 个章节、原文段落、AI 讲解和学习进度会一并删除，无法恢复。` +
        `如果这是扫描件教材，再想看得重新上传并重新识别。`,
    );
    if (!ok) return;

    try {
      await api.deleteBook(book.id);
    } catch (error) {
      toast(error.message || '删除教材失败');
      return;
    }

    let list = [];
    try {
      list = await refreshBooks();
    } catch {
      // 书已经删掉了，只是列表没刷出来。不用为此报错——重开弹窗会重读服务端。
    }
    // 删的是当前教材就顺手切到第一本：BookProvider 的兜底逻辑本来也不会让死 id 生效，
    // 但显式切换能把 localStorage 里的那个死 id 一起换掉。
    if (book.id === currentBookId && list.length) setCurrentBookId(list[0].id);
    toast(`已删除《${name}》`);
  };

  /** 正在识别扫描件时不让再上传：本机 CPU 就那么多，两本一起识别只会互相拖慢，
   *  而且这个弹窗同一时刻只跟得住一个任务。 */
  const ocrRunning = Boolean(taskId);

  return (
    <div className="modal open" role="dialog" aria-modal="true" aria-label="选择学习材料" onClick={close}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={close} aria-label="关闭">
          ×
        </button>
        <div className="eyebrow">选择学习材料</div>
        <h2 style={{ marginTop: 7 }}>更换教材</h2>
        {notice && (
          <div className="upload-warning" role="alert">
            <b>{notice.heading}</b>
            <p>{notice.text}</p>
            <p className="upload-warning-tip">{notice.tip}</p>
            <button type="button" className="warning-ok" onClick={close}>
              {notice.action}
            </button>
          </div>
        )}
        {/* 刻意不给这个块加 role="status"：toast 已经占了那个 role，而进度每
            1.5 秒就换一次文本，让读屏器一直播报也很吵。真正该被读出来的是
            里面的 <progress> 本身。 */}
        {task && (
          <div className="upload-progress">
            <b>
              《{task.title}》是扫描件，正在识别：
              {task.totalPages ? `${task.donePages} / ${task.totalPages} 页` : '正在排队…'}
            </b>
            <progress
              value={task.donePages}
              max={task.totalPages || 1}
              aria-label="扫描件识别进度"
            />
            <p className="upload-progress-tip">
              扫描件没有文字层，要逐页 OCR 识字，一本几百页的书大约十几分钟。可以先关掉这个窗口继续学习，
              识别完成后会通知你；识别期间本机不再接第二本。
            </p>
          </div>
        )}
        <div className="book-choices">
          {books.map((book) => (
            <div key={book.id} className="book-choice">
              {/* testid 给的是「选择」这个动作，点击区里不含删除——按书名查按钮会同时
                  命中删除按钮（它的 aria-label 里也有书名），测试自己得能分得清。 */}
              <button
                className="book-choice-main"
                data-testid={`book-choice-${book.id}`}
                onClick={() => choose(book)}
              >
                <span>
                  <b>
                    {book.title} · {book.edition || '第 3 版'}
                  </b>
                  <br />
                  <small>
                    {book.author} · {book.chapters.length} 个已识别章节
                  </small>
                  {/* 提示随教材一起存库，重开弹窗仍然看得到，不用凭记忆回想 */}
                  {book.contentWarning ? <em className="choice-warning">⚠ 内容可能没读全</em> : null}
                </span>
                <span>{book.id === currentBookId ? '当前' : '→'}</span>
              </button>
              {/* 删除按钮只能当兄弟节点，不能塞进上面那个按钮里：button 套 button 是
                  非法 HTML，浏览器会把内层甩到外层之外，点击区域随即错位。 */}
              <button
                type="button"
                className="book-delete"
                aria-label={`删除《${book.title}》`}
                onClick={() => remove(book)}
              >
                删除
              </button>
            </div>
          ))}
          <input
            ref={inputRef}
            className="upload-input"
            type="file"
            accept=".pdf,.docx,.txt,.md,application/pdf,text/plain,text/markdown"
            onChange={upload}
            aria-label="选择教材文件"
          />
          <button
            className="upload"
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={uploading || ocrRunning}
          >
            {uploading
              ? '正在上传并识别目录…'
              : ocrRunning
                ? '识别中，暂不能再上传'
                : '＋ 上传新教材（PDF / Word / 文本）'}
          </button>
          <p className="upload-hint">
            {FORMAT_HINT}；扫描件（图片型 PDF）会自动用 OCR 识别，速度较慢但不用自己转换。
          </p>
        </div>
      </div>
    </div>
  );
}
