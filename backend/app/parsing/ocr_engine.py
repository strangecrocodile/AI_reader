"""OCR 引擎：把一页扫描图转成带坐标的文本行。

只做「图 → 文字行」这一件事，不碰 PDF、不碰结构。结构重建在 `parsing/ocr_pdf.py`，
两者分开是为了让测试能注入假引擎——识别质量是模型的事，结构还原才是我们的逻辑。

依赖是**可选**的（见 `requirements-ocr.txt`）：没装时 `RapidOcrEngine.try_create`
返回 None，调用方降级成一条带安装指引的提示，而不是让整个后端起不来。
这与 `rag/retrieval.py` 对待向量服务的口径一致。
"""
import threading
from typing import List, NamedTuple, Optional, Protocol, Sequence

#: 传给 onnxruntime 的线程数。默认 -1（用满所有核心）在 Web 服务里会饿死其它请求。
DEFAULT_THREADS = 4


class OcrLine(NamedTuple):
    """一行识别结果。坐标是**图像像素**坐标，原点在左上角。"""

    text: str
    score: float
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def width(self) -> float:
        return self.x1 - self.x0


class OcrEngine(Protocol):
    """引擎接口。实现只要能被 `ocr_pdf` 调用即可，测试用假对象注入。"""

    name: str

    def recognize(self, image_png: bytes) -> List[OcrLine]:
        """识别一页 PNG 图片，返回文本行（顺序不作要求，调用方会重排）。"""
        ...


class RapidOcrEngine:
    """基于 RapidOCR（PP-OCRv6 + onnxruntime）的本地实现。

    模型随 wheel 分发（约 31MB），**默认构造不联网**。前提是不要传
    `model_type` / `ocr_version` / `lang_type` 这三个参数——一旦传了，
    RapidOCR 会转去 ModelScope 下载模型，离线环境直接挂。见 `_PARAMS`。

    引擎对象在首次识别时才创建：加载模型要 2～3 秒，不该让每次启动都付这个成本。
    """

    name = "rapidocr"

    def __init__(self, dpi: int = 200, threads: int = DEFAULT_THREADS):
        self.dpi = dpi
        self.threads = threads
        self._engine = None
        self._lock = threading.Lock()

    @classmethod
    def try_create(cls, settings, **_kwargs) -> Optional["RapidOcrEngine"]:
        """配置允许且依赖装得上时返回引擎，否则返回 None（调用方据此给提示）。

        只验证「包能不能 import」，不加载模型——那是 `_ensure_engine` 的事。
        """
        if not getattr(settings, "ocr_configured", False):
            return None
        try:
            import rapidocr  # noqa: F401
        except Exception:  # noqa: BLE001 —— 没装或装坏了都当成「不可用」
            return None
        return cls(dpi=getattr(settings, "ocr_dpi", 200), threads=getattr(settings, "ocr_threads", DEFAULT_THREADS))

    def _ensure_engine(self):
        if self._engine is not None:
            return self._engine
        with self._lock:
            if self._engine is None:
                from rapidocr import RapidOCR

                self._engine = RapidOCR(params={"EngineConfig.onnxruntime.intra_op_num_threads": self.threads})
        return self._engine

    def recognize(self, image_png: bytes) -> List[OcrLine]:
        """识别一页。

        入参必须是 **PNG 字节**，不能是 numpy 数组：RapidOCR 的
        `load_image.convert_img` 只对解码类输入（bytes/路径/PIL）做 RGB→BGR 修正，
        直接喂 numpy 数组会按 BGR 解释，导致红蓝通道互换、识别质量下降。
        """
        engine = self._ensure_engine()
        out = engine(image_png)
        # 无文字时 boxes/txts 可能是 None（也可能是 numpy 数组，不能用 `or` 判空）
        boxes = getattr(out, "boxes", None)
        txts = getattr(out, "txts", None)
        scores = getattr(out, "scores", None)
        if boxes is None or txts is None:
            return []
        if scores is None:
            scores = [0.0] * len(txts)

        lines: List[OcrLine] = []
        for box, text, score in zip(boxes, txts, scores):
            text = (text or "").strip()
            if not text:
                continue
            lines.append(
                OcrLine(
                    text=text,
                    score=float(score),
                    x0=min(float(p[0]) for p in box),
                    y0=min(float(p[1]) for p in box),
                    x1=max(float(p[0]) for p in box),
                    y1=max(float(p[1]) for p in box),
                )
            )
        return lines


def lines_to_text(lines: Sequence[OcrLine]) -> str:
    """按阅读顺序把行拼成段落文本（供 `_split_paragraphs` 复用切段逻辑）。

    顺序假设：先上下、后左右。**单栏假设**——双栏教材的左右栏会被交错读进来，
    v1 不处理（见 `ocr_pdf` 的说明）。
    """
    ordered = sorted(lines, key=lambda ln: (ln.y0, ln.x0))
    return "\n".join(ln.text for ln in ordered)
