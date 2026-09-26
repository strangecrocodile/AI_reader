"""生成示例演示教材 PDF（内容为团队原创，版权合规）。

用法：backend/.venv/Scripts/python.exe scripts/make_demo_pdf.py [输出路径]
默认输出到 backend/data/demo_textbook.pdf

构建逻辑在 `app/services/demo.py` —— 后端在空库启动时也要用它自动导入一本，
放在这里会被 app 反向依赖脚本。本文件只留命令行入口。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.demo import build_demo_pdf  # noqa: E402

if __name__ == "__main__":  # pragma: no cover
    out = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else Path(__file__).resolve().parents[1] / "data" / "demo_textbook.pdf"
    )
    print(build_demo_pdf(out))
