"""Pydantic 请求模型。"""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

#: 学习事件类型：进入章节 / 读到段落 / 提问 / 标记学完 / 自测作答
EventKind = Literal["open", "read", "ask", "complete", "quiz"]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    bookId: str
    chapterId: str
    selectedText: Optional[str] = None


class ProgressRequest(BaseModel):
    status: str = Field(pattern="^(learning|learned)$")
    mastery: float = Field(ge=0, le=100)


class EventRequest(BaseModel):
    """一次学习事件上报；掌握度由后端按事件重算，前端不再自己编数字。"""

    kind: EventKind
    anchorIds: List[str] = Field(default_factory=list, max_length=200)
    question: Optional[str] = Field(default=None, max_length=500)
    correct: Optional[bool] = None

    @model_validator(mode="after")
    def _check_payload(self) -> "EventRequest":
        if self.kind == "read" and not self.anchorIds:
            raise ValueError("read 事件必须带 anchorIds")
        if self.kind == "ask" and not (self.question or "").strip():
            raise ValueError("ask 事件必须带 question")
        if self.kind == "quiz" and self.correct is None:
            raise ValueError("quiz 事件必须带 correct")
        return self
