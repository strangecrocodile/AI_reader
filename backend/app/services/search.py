"""全书搜索：给「我记得这句话在书里，但忘了在第几章」这件事一个入口。

## 为什么要有它

这个产品此前**只有**通过 `/api/ask` 才能碰到正文检索：想问「书里哪儿讲过梯度消失」，
只能去右栏当一个问题提，然后从回答的依据里倒推位置。可「定位」和「提问」是两件事——
前者用户心里已经有目标，只想找到它；给他一段 AI 总结，反而多绕一步。

搜索走的是**和问答同一条检索链路**（`RetrievalService` 的 BM25 + 可选向量 RRF 融合），
所以命中理由和排序口径跟依据判定一致，不存在「搜索找得到、问答说没讲过」这种自相矛盾。

与问答的唯一区别是不做本章加权：结果不该随用户当前停在哪一章而变。
"""
import logging
from typing import Any, Dict, List

from ..db import Database

logger = logging.getLogger(__name__)

#: 一次最多返回多少条。搜索是给人看的列表，不是喂模型的证据集。
DEFAULT_LIMIT = 20
MAX_LIMIT = 50


def search_full_text(
    db: Database,
    retrieval,
    book_id: str,
    query: str,
    limit: int = DEFAULT_LIMIT,
) -> Dict[str, Any]:
    """在整本教材里检索，返回 `{query, total, hits}`。

    每条命中都带 `anchorId` 与 `chapterId`：前端据此跳到对应章节并高亮那段原文，
    复用问答「教材依据」那条已经跑通的跳转逻辑。
    """
    text = (query or "").strip()
    if not text:
        # 空查询不是错误：用户刚清空输入框而已，给一张空列表比弹一个报错合适
        return {"query": "", "total": 0, "hits": []}

    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    scored = retrieval.search_whole_book(book_id, text, k=limit)

    chapters = {c["id"]: c for c in db.chapters_of(book_id)}
    # 只取命中所在的章，不为了几条结果把整本书的段落都读一遍
    sections: Dict[str, Dict[str, Any]] = {}
    for chapter_id in {hit["chapter_id"] for hit in scored}:
        for section in db.sections_of(book_id, chapter_id):
            sections[section["id"]] = section

    hits: List[Dict[str, Any]] = []
    for hit in scored:
        section = sections.get(hit["section_id"])
        if section is None:
            continue  # 索引与库不同步（理论上不该发生），跳过比抛错好
        chapter = chapters.get(hit["chapter_id"], {})
        hits.append(
            {
                "anchorId": hit["section_id"],
                "chapterId": hit["chapter_id"],
                "chapterTitle": chapter.get("title", ""),
                "page": section.get("page", 1),
                "text": section.get("text", ""),
                "kind": section.get("kind", "p"),
                "score": hit["score"],
            }
        )
    return {"query": text, "total": len(hits), "hits": hits}
