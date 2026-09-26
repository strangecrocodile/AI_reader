"""数据目录的回收：找出并删掉没有任何库记录指向的文件。

## 为什么需要它

原文件与插图是**先落盘、后写库**的（见 `services/ingest`、`parsing/assets`），而删除
教材直到最近才学会一并清理磁盘（`services/ingest.delete_book_files`）。于是历史数据里
会积下一批孤儿：库里 3 本书，`data/sources/` 可能有上千个文件。

它们不只是占地方——那些是**他人教材的副本**，留着有合规含义（见 `docs/后端设计文档.md`
第 11 节），所以清理要能被复核、能重复跑，而不是手敲一条 `Remove-Item`。

## 只删「确定是我们自己命名、且已无归属」的文件

命名约定是判断归属的唯一依据，两种文件都能从名字反推作者是谁：

- 原文件：`{book_id}.{fmt}`，`book_id` 是 8 位小写十六进制（`uuid4().hex[:8]`）；
- 插图：`{book_id}-p{页码}-{序号}.{ext}`。

名字**不符合**这两条约定的文件一律不动（`unrecognized`），只报告。可能是用户自己放进去
的东西，也可能是将来换了命名规则的产物——按「看起来像孤儿」就删，是在拿别人的数据赌。
"""
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from ..db import Database

logger = logging.getLogger(__name__)

#: 教材 id：`uuid4().hex[:8]`，小写十六进制。原文件与插图都以它开头/命名。
BOOK_ID_PATTERN = r"[0-9a-f]{8}"
_SOURCE_NAME_RE = re.compile(rf"^({BOOK_ID_PATTERN})\.(pdf|docx|doc|text)$")
_ASSET_NAME_RE = re.compile(rf"^({BOOK_ID_PATTERN})-")


def _files(directory) -> List[Path]:
    path = Path(directory)
    if not path.is_dir():
        return []
    return sorted(p for p in path.iterdir() if p.is_file())


def scan(db: Database, settings) -> Dict[str, List[Path]]:
    """列出孤儿文件。**不删任何东西**，调用方据此决定。

    返回三类：
    - `sources` / `assets`：认得出归属、且那本教材已经不在库里 → 可删；
    - `unrecognized`：名字不符合命名约定 → 绝不删，只报告。

    原文件这里还有一条**刻意保守**的规则：教材还在库里、但 `source_name` 没指向这个
    文件时，不算孤儿，只进 `unrecognized`。理由是那种状态可能来自一个 bug（列被清空），
    而磁盘上那份很可能是用户教材的唯一副本——「按名字猜它没用」就去删，是在拿别人的
    数据赌。真正需要腾空间时，这类文件的数量与文件名都会报出来，由人判断。
    """
    books = db.list_books()
    live_ids = {str(b.get("id") or "") for b in books}
    kept_sources = {Path(b.get("source_name") or "").name for b in books}
    kept_sources.discard("")

    sources: List[Path] = []
    assets: List[Path] = []
    unrecognized: List[Path] = []

    for path in _files(settings.sources_dir):
        match = _SOURCE_NAME_RE.match(path.name)
        if match is None:
            unrecognized.append(path)
        elif match.group(1) not in live_ids:
            sources.append(path)
        elif path.name not in kept_sources:
            # 教材还在，只是没指向它：可疑，但不动
            unrecognized.append(path)

    for path in _files(settings.assets_dir):
        match = _ASSET_NAME_RE.match(path.name)
        if match is None:
            unrecognized.append(path)
        elif match.group(1) not in live_ids:
            assets.append(path)

    return {"sources": sources, "assets": assets, "unrecognized": unrecognized}


def delete_orphans(db: Database, settings) -> Dict[str, int]:
    """删掉孤儿文件，返回各类的处理个数。认不出的文件不动。"""
    found = scan(db, settings)
    removed = {"sources": 0, "assets": 0, "unrecognized": 0}
    for kind in ("sources", "assets"):
        for path in found[kind]:
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            except OSError as exc:  # 被占用 / 无权限：跳过，别中断整轮清理
                logger.warning("清理孤儿文件失败，已跳过：%s（%s）", path, exc)
                continue
            removed[kind] += 1
    removed["unrecognized"] = len(found["unrecognized"])
    return removed


def describe(found: Dict[str, List[Path]], sample: int = 3) -> str:
    """给人看的一行摘要 + 若干样例，用于 `--dry-run` 输出。"""
    lines = [
        f"可清理：原文件 {len(found['sources'])} 个，插图 {len(found['assets'])} 个",
        f"认不出归属、不会动：{len(found['unrecognized'])} 个",
    ]
    for kind in ("sources", "assets"):
        for path in found[kind][:sample]:
            lines.append(f"  [{kind}] {path.name}")
        if len(found[kind]) > sample:
            lines.append(f"  [{kind}] … 其余 {len(found[kind]) - sample} 个")
    return "\n".join(lines)
