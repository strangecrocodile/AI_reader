"""Pydantic 请求模型。"""
from typing import Optional

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    bookId: str
    chapterId: str
    selectedText: Optional[str] = None


class ProgressRequest(BaseModel):
    status: str = Field(pattern="^(learning|learned)$")
    mastery: float = Field(ge=0, le=100)
