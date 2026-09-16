"""扫描件 OCR 的异步任务：建任务 → 后台线程识别 → 推进度 → 入库 / 全量失败。

## 为什么是「任务表 + 后台线程」而不是别的东西

- **不用 `BackgroundTasks`**：`TestClient` 下它会同步内联执行，测试会真的跑一遍 ONNX 识别。
- **不用 `asyncio.to_thread`**：它用默认执行器（最多 32 线程），OCR 是 CPU 密集的，
  并发几本就会把整个应用拖死。这里全局只有一个 worker。
- **状态落 SQLite 而不是 `app.state` 内存字典**：进程重启后内存里的任务会消失，
  前端轮询会拿到 404，只能显示「任务不存在」；落库则能诚实回报「已中断，请重新上传」
  （见 `Database.fail_stale_ocr_tasks`）。

## 失败策略：全有或全无

识别到一半失败时**一行都不写库**。因为 `store_parsed_book` 在 `ocr_pdf_bytes` 完整
返回之后才被调用，而它内部又是单事务。半本书入库会破坏产品最核心的承诺——
「每条回答都能回到原文核对」：溯源会把 400 页书的前 120 页当成完整依据展示，
而前端唯一的补救按钮是「知道了，先这样看」，太容易被划过去。
"""
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from ..db import Database
from ..parsing.ocr_engine import OcrEngine, RapidOcrEngine
from ..parsing.ocr_pdf import ocr_pdf_bytes
from ..parsing.pdf import probe_pdf
from .ingest import OCR_SOURCE_NOTE, SCANNED_NO_OCR_MESSAGE, store_parsed_book

logger = logging.getLogger(__name__)

PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"

#: 进度写库的最小间隔（秒）。前端 1.5 秒轮询一次，写得更勤没有意义，
#: 只会让 SQLite 白白抖动。最后一页强制写，保证终值准确。
PROGRESS_WRITE_INTERVAL = 1.0


class OcrUnavailable(Exception):
    """认出是扫描件，但服务端没有可用的 OCR。调用方据此返回带指引的提示。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def task_to_frontend(task: Dict[str, Any]) -> Dict[str, Any]:
    """任务行 → 前端结构（camelCase，与 `serializers.py` 同一约定）。"""
    total = task.get("total_pages", 0) or 0
    done = task.get("done_pages", 0) or 0
    return {
        "id": task["id"],
        "status": task["status"],
        "filename": task.get("filename", ""),
        "title": task.get("title", ""),
        "totalPages": total,
        "donePages": done,
        "percent": round(done * 100 / total) if total else 0,
        "bookId": task.get("book_id", "") or "",
        "message": task.get("message", ""),
        "createdAt": task.get("created_at", ""),
        "updatedAt": task.get("updated_at", ""),
    }


def _run_in_daemon_thread(job: Callable[[], None]) -> None:
    """默认的执行方式：跑在一个守护线程里。

    用守护线程而不是 `ThreadPoolExecutor`：后者的工作线程不是守护线程，
    解释器退出时会 join 它们——一本 400 页的书要跑十几分钟，等于 Ctrl+C 之后
    进程赖着不走。OCR 任务本来就是可以放弃的（重启后对账会标成「已中断」）。
    """
    threading.Thread(target=job, name="ocr-worker", daemon=True).start()


class OcrTaskService:
    """扫描件 OCR 任务的唯一入口。挂载在 `app.state.ocr`。"""

    def __init__(
        self,
        db: Database,
        settings,
        retrieval=None,
        engine_factory: Optional[Callable[[], Optional[OcrEngine]]] = None,
        runner: Optional[Callable[[Callable[[], None]], None]] = None,
    ):
        self.db = db
        self.settings = settings
        self.retrieval = retrieval
        self._engine_factory = engine_factory or (lambda: RapidOcrEngine.try_create(settings))
        self._runner = runner or _run_in_daemon_thread
        self._engine: Optional[OcrEngine] = None
        self._engine_resolved = False
        self._engine_lock = threading.Lock()

    # ---- 引擎 ----

    def engine(self) -> Optional[OcrEngine]:
        """惰性解析一次并缓存。只 import 包、不加载模型，所以放在请求路径上也便宜；
        真正加载模型（2～3 秒）发生在工作线程第一次识别时。"""
        with self._engine_lock:
            if not self._engine_resolved:
                try:
                    self._engine = self._engine_factory()
                except Exception:  # noqa: BLE001 —— 依赖装坏了也按「不可用」处理
                    logger.exception("OCR 引擎初始化失败，按不可用处理")
                    self._engine = None
                self._engine_resolved = True
            return self._engine

    # ---- 提交 ----

    def submit(
        self,
        data: bytes,
        filename: str = "",
        title: str = "",
        probe=None,
    ) -> Dict[str, Any]:
        """建任务并排队。**只有扫描件会走到这里**，调用方已用 `probe_pdf` 判过。

        `probe` 允许由调用方传入，省掉一次重复抽样；不传就自己探一次。
        返回任务结构（调用方回 202）。
        """
        probe = probe or probe_pdf(data)
        if probe is None or not probe.scanned:
            raise ValueError("不是扫描件，应走常规解析路径")
        if self.engine() is None:
            raise OcrUnavailable(SCANNED_NO_OCR_MESSAGE)

        task_id = uuid.uuid4().hex[:8]
        now = _now()
        task = {
            "id": task_id,
            "status": PENDING,
            "filename": filename,
            "title": title,
            "total_pages": probe.pages,
            "done_pages": 0,
            "book_id": "",
            "message": "",
            "created_at": now,
            "updated_at": now,
        }
        self.db.add_ocr_task(task)
        self._runner(lambda: self._work(task_id, data, filename, title))
        # 回读而不是直接返回上面那个快照：跑的是哪条 runner 只有调用方知道，
        # 同步 runner（测试）下活儿此刻已经干完，返回 `pending` 就是在撒谎。
        return self.get(task_id) or task_to_frontend(task)

    def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = self.db.get_ocr_task(task_id)
        return task_to_frontend(task) if task else None

    # ---- 干活 ----

    def _work(self, task_id: str, data: bytes, filename: str, title: str) -> None:
        """工作线程主体。任何异常都在这里收口成 `failed`，绝不让线程静默死掉。"""
        engine = self.engine()
        if engine is None:  # 提交时还在，跑到时没了——理论上不会，兜一下
            self._fail(task_id, 0, 0, SCANNED_NO_OCR_MESSAGE)
            return

        self.db.update_ocr_task(task_id, status=RUNNING, updated_at=_now())
        state = {"done": 0, "total": 0, "written_at": 0.0}

        def on_page(done: int, total: int) -> None:
            state["done"], state["total"] = done, total
            now = time.monotonic()
            if done < total and now - state["written_at"] < PROGRESS_WRITE_INTERVAL:
                return
            state["written_at"] = now
            self.db.update_ocr_task(task_id, done_pages=done, updated_at=_now())

        try:
            parsed = ocr_pdf_bytes(
                data,
                engine,
                default_title=title or filename or "未命名教材",
                dpi=getattr(self.settings, "ocr_dpi", 200),
                on_page=on_page,
            )
            # 到这一步之前一行都没写库；下面这次调用是单事务，所以要么整本、要么没有
            info = store_parsed_book(
                self.db,
                parsed,
                note=OCR_SOURCE_NOTE,
                default_title=title or filename or "未命名教材",
            )
        except Exception as e:  # noqa: BLE001 —— 线程里没有上层，必须自己收口
            logger.exception("OCR 任务 %s 失败", task_id)
            self._fail(task_id, state["done"], state["total"], str(e))
            return

        if self.retrieval is not None:
            try:
                self.retrieval.invalidate_book(info["id"])
            except Exception:  # noqa: BLE001 —— 缓存失效失败不该让教材「识别失败」
                logger.exception("OCR 入库后清理检索缓存失败：%s", info["id"])

        total = state["total"]  # 每页都会回调，走到这里必定等于总页数
        self.db.update_ocr_task(
            task_id,
            status=DONE,
            book_id=info["id"],
            done_pages=total,
            total_pages=total,
            message="",
            updated_at=_now(),
        )

    def _fail(self, task_id: str, done: int, total: int, reason: str) -> None:
        """写成失败，并把「跑到第几页」说清楚——用户据此判断要不要重传。"""
        if total:
            message = f"已识别 {done}/{total} 页后失败：{reason}"
        else:
            message = f"识别失败：{reason}"
        self.db.update_ocr_task(
            task_id,
            status=FAILED,
            done_pages=done,
            message=message,
            updated_at=_now(),
        )
