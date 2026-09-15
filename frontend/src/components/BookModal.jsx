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

/** 轮询间隔。后端每识别一页就写一次库，1.5 秒足够跟手，又不至于把 SQLite 敲出火星。 */
const OCR_POLL_INTERVAL = 1500;
/** 兜底上限。几百页的书也就十几分钟，45 分钟到这儿基本是出事了——无限转圈比停下来更糟。 */
const OCR_POLL_TIMEOUT = 45 * 60 * 1000;

/** 更换教材弹窗：可切换已有教材，也可上传 PDF / Word / 纯文本教材。 */
export default function BookModal({ open, onClose }) {
  const { books, currentBookId, setCurrentBookId, refreshBooks } = useBooks();
  const toast = useToast();
  const inputRef = useRef(null);
  const [uploading, setUploading] = useState(false);
  const [notice, setNotice] = useState(null);
  const [taskId, setTaskId] = useState(null);
  const [task, setTask] = useState(null);

  /**
   * 轮询扫描件识别进度，直到 `done` / `failed` / 任务消失 / 超时。
   *
   * **这个 effect 必须声明在下面那句 `if (!open) return null` 之前**：Hook 不能在
   * 渲染中途被跳过，放到早退之后，一开一合弹窗 React 就会抛错。
   * 同理它**不依赖 `open`**：识别要跑十几分钟，中途关掉弹窗是正常操作，关掉之后
   * 照样得继续问，才能在他回来时（或通过 toast）把结果告诉他。
   *
   * 依赖数组刻意只写 `[taskId]`：`task` 每 1.5 秒就是一个新对象，把 `task` 或
   * 它的 `donePages` 放进来，等于每轮都重建 effect——那 45 分钟的上限会被
   * 一次次重置，永远兜不住。闭包里的 `refreshBooks` / `toast` 虽然身份会变，
   * 但它们操作的都是 Provider 里的状态，用哪一次渲染的版本结果一样。
   */
  useEffect(() => {
    if (!taskId) return undefined;
    const startedAt = Date.now();
    let timer = null;
    let cancelled = false;

    const stop = () => {
      timer = null;
      setTaskId(null);
      setTask(null);
    };

    const tick = async () => {
      if (cancelled) return;
      if (Date.now() - startedAt > OCR_POLL_TIMEOUT) {
        stop();
        toast('扫描件识别超过 45 分钟仍未结束，已停止等待；稍后刷新教材列表看看是否已经导入');
        return;
      }

      let latest;
      try {
        latest = await api.fetchOcrTask(taskId);
      } catch {
        // 网络抖动而已，不当成失败，下一轮再问
        timer = setTimeout(tick, OCR_POLL_INTERVAL);
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

      timer = setTimeout(tick, OCR_POLL_INTERVAL);
    };

    timer = setTimeout(tick, OCR_POLL_INTERVAL);
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
            <button key={book.id} className="book-choice" onClick={() => choose(book)}>
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
