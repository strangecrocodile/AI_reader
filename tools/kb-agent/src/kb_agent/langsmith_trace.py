"""LangSmith 追踪接入（可选，P3 观测）。

启用条件：.env/环境变量配置了 LANGCHAIN_API_KEY 且 LANGCHAIN_TRACING_V2=true。
- 启用后：KBAgent.run / KBAgent.ask / DeepSeek 调用会用 langsmith @traceable
  包装，运行轨迹上报 LangSmith（项目名取 LANGCHAIN_PROJECT，缺省 kb-agent）；
- 未配置/初始化失败：所有包装“透传”原函数，零开销，不影响离线测试。
"""
from __future__ import annotations

import logging
import os

from .config_env import ensure_env

logger = logging.getLogger("kb_agent.langsmith_trace")

_enabled = False
_traceable_impl = None
_project = ""


def enable_langsmith() -> bool:
    """读取 .env/环境，若可启用则初始化 traceable，返回是否启用。

    每次调用都会按当前环境重新判断（不缓存），便于测试隔离与运行时开关。
    """
    global _enabled, _traceable_impl, _project
    ensure_env()
    key = os.getenv("LANGCHAIN_API_KEY", "")
    tracing = os.getenv("LANGCHAIN_TRACING_V2", "true").strip().lower() in ("1", "true", "yes")
    if not (key and tracing):
        _traceable_impl = None
        _enabled = False
        return False
    try:
        from langsmith import traceable

        _traceable_impl = traceable
        _project = os.getenv("LANGCHAIN_PROJECT", "") or "kb-agent"
        os.environ.setdefault("LANGCHAIN_PROJECT", _project)
        _enabled = True
        logger.info("LangSmith 追踪已启用：project=%s", _project)
        return True
    except Exception as exc:  # pragma: no cover
        logger.warning("LangSmith 初始化失败：%s（继续无追踪运行）", exc)
        _traceable_impl = None
        _enabled = False
        return False


def wrap(name: str, run_type: str = "chain"):
    """装饰器：启用时用 langsmith.traceable 包装；否则原样返回。"""

    def deco(fn):
        if _traceable_impl is None:
            return fn
        return _traceable_impl(fn, name=name, run_type=run_type)

    return deco


def is_enabled() -> bool:
    return _enabled
