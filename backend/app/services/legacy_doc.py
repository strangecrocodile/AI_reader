"""旧版 Word（.doc）支持：交给 LibreOffice 转成 .docx 再走既有解析链路。

`.doc` 是 OLE 二进制复合文档，`python-docx` 读不了。要保留行内版式（粗体、上下标…）
就只能靠能理解该格式的转换器，而 LibreOffice 是唯一常见且免费的选择：

- **不做纯文本抽取**（antiword / catdoc 那类）：它们拿不到 run 级格式，
  与本次「还原原文件版式」的目标直接冲突——转出来还是没格式的一堆字；
- **装不上就明说**：LibreOffice 是可选依赖，缺失时给一句能照做的提示
  （另存为 .docx），而不是抛一个看不懂的转换错误。

检测结果做了缓存：每次上传都去 `soffice --version` 起一个进程太浪费。
"""
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

#: 可用二进制名（Windows 是 soffice.exe，Linux/macOS 常见 soffice 或 libreoffice）
_BINARY_NAMES = ("soffice", "libreoffice")
#: 允许用环境变量显式指定路径（LibreOffice 未必在 PATH 里）
_ENV_VAR = "AI_READER_SOFFICE"

#: 转换给足超时：大文档首次转换要几十秒，但也不能无限等
CONVERT_TIMEOUT_SECONDS = 180

#: 缺失 LibreOffice 时给用户看的提示
MISSING_MESSAGE = (
    "服务器未安装 LibreOffice，暂时无法直接解析 .doc；"
    "请在 Word 里另存为 .docx 后重新上传"
)

#: 缓存探测结果。None 表示「还没探过」——不能只缓存成功，失败也要缓存，
#: 否则每个 .doc 上传都会白起一次进程。
_soffice_path: Optional[str] = None
_probed = False


def reset_cache() -> None:
    """清掉二进制探测缓存（测试用；也让运维在装上 LibreOffice 后能即时生效）。"""
    global _soffice_path, _probed
    _soffice_path = None
    _probed = False


def find_soffice() -> Optional[str]:
    """找到 soffice 可执行文件；找不到返回 None（结果会被缓存）。"""
    global _soffice_path, _probed
    if _probed:
        return _soffice_path
    _probed = True

    override = os.getenv(_ENV_VAR, "").strip()
    if override:
        # 显式指定的路径不再验证：运维给的就按他给的用，报错也更直白
        _soffice_path = override
        logger.info("使用 %s 指定的 LibreOffice：%s", _ENV_VAR, override)
        return _soffice_path

    for name in _BINARY_NAMES:
        found = shutil.which(name)
        if found:
            _soffice_path = found
            logger.info("找到 LibreOffice：%s", found)
            return _soffice_path
    logger.info("未找到 LibreOffice，.doc 将无法解析")
    return None


def is_available() -> bool:
    return find_soffice() is not None


def convert_doc_to_docx(data: bytes) -> bytes:
    """把 .doc 字节流转成 .docx 字节流。

    用临时目录做中转：LibreOffice 只能按**文件**工作，且会就地写出同名 .docx。
    转换结果读回内存后临时目录即删，因此不残留中间文件。
    """
    binary = find_soffice()
    if binary is None:
        raise ValueError(MISSING_MESSAGE)

    with tempfile.TemporaryDirectory(prefix="ai-reader-doc-") as workdir:
        source = Path(workdir) / "input.doc"
        source.write_bytes(data)
        completed = subprocess.run(  # noqa: S603 —— 参数是拼接好的列表，不经 shell
            [
                binary,
                "--headless",
                "--norestore",
                "--convert-to",
                "docx",
                "--outdir",
                workdir,
                str(source),
            ],
            capture_output=True,
            timeout=CONVERT_TIMEOUT_SECONDS,
            check=False,
        )
        produced = Path(workdir) / "input.docx"
        if not produced.is_file():
            detail = (completed.stderr or completed.stdout or b"").decode(
                "utf-8", errors="replace"
            ).strip()
            logger.warning("LibreOffice 转换 .doc 失败：%s", detail[:500])
            raise ValueError(
                "无法解析这个 .doc 文件（可能已损坏或受密码保护）；"
                "请在 Word 里另存为 .docx 后重试"
            )
        return produced.read_bytes()
