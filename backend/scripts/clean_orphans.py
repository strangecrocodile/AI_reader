"""清理 data/sources 与 data/assets 里没有任何库记录指向的孤儿文件。

用法（在 backend 目录下执行）：

    .venv\\Scripts\\python.exe scripts\\clean_orphans.py            # 只报告，不删
    .venv\\Scripts\\python.exe scripts\\clean_orphans.py --apply    # 真删

删之前务必先跑一次不带 `--apply` 的：它会列出待删数量与样例，并单独报出
「认不出归属、一律不碰」的文件数。判定规则与理由见 `app/services/maintenance.py`。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.services import maintenance  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="清理孤儿文件（默认只报告，不删）")
    parser.add_argument("--apply", action="store_true", help="真的删除；不加只做 dry-run")
    args = parser.parse_args(argv)

    db = Database(settings.db_path)
    db.init()

    found = maintenance.scan(db, settings)
    print(maintenance.describe(found))

    if not args.apply:
        print("\n这是 dry-run，什么都没删。确认无误后加 --apply 再跑一次。")
        return 0

    removed = maintenance.delete_orphans(db, settings)
    print(f"\n已删除：原文件 {removed['sources']} 个，插图 {removed['assets']} 个")
    print(f"保留（认不出归属）：{removed['unrecognized']} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
