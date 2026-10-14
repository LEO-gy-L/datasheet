# -*- coding: utf-8 -*-
"""
问答历史业务
============
两个方向：

    写 —— 助理页每问一次，后端答完顺手写一行（由 api/qa.py 调用）
    读 —— 历史问答页倒序列出、按关键词搜、删除

⚠️ 存储与网络的分界（这个文件最关键的设计）：
    数据库里 sources 是**一坨 JSON 文本**，给前端时必须是**真正的数组**。
    转换只发生在 `_to_dict()` 这一处 —— 别让 json.dumps / json.loads 散落在各处，
    否则迟早出现"某一处忘了 loads，前端拿到字符串却当成数组用"的问题。

⚠️ 权限边界：所有函数都要求传 user_id，并且**只查这个人的数据**。
    这里的 where 条件就是安全边界，少写一个 filter 就等于"任何人能看到全部人的历史"。
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from backend.app.common.exceptions import NotFoundError
from backend.app.models.qa_history import QaHistory
from backend.app.utils.time_fmt import fmt, now

# 一次最多返回多少条。防止某天历史攒了几万条，一个请求把内存和网络打满。
# 分页由前端的"加载更多"配合 offset 实现。
MAX_LIMIT = 200


def record(
    db: Session,
    *,
    user_id: int,
    question: str,
    answer: str,
    sources: list[str],
    source_doc: str | None,
    seconds: float,
) -> QaHistory | None:
    """写一条历史。

    ⚠️ 返回 None 表示"没写成功"，**并且绝不抛异常**。
       为什么：这个函数是在 /api/ask 回答完之后调用的。
       用户已经拿到答案了，这时候"记日志失败"不该把整个请求变成 500 ——
       那等于告诉用户"你这个问题失败了"，但其实答出来了。
       历史记录是**附属品**，它的失败不能连累主流程。（写法叫"尽力而为"best-effort）
    """
    try:
        row = QaHistory(
            user_id=user_id,
            question=question,
            answer=answer,
            # 数组 -> JSON 文本。ensure_ascii=False 保证中文按原样存
            # （否则会存成 \u7b2c37\u9875 这种，虽然读出来还是中文，但直接看数据库完全没法读）
            sources=json.dumps(sources, ensure_ascii=False),
            source_doc=source_doc,
            seconds=seconds,
            created_at=now(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    except Exception:      # noqa: BLE001 —— 这里就是要兜住一切，见上面说明
        db.rollback()
        return None


def list_mine(
    db: Session,
    user_id: int,
    keyword: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """我的历史，按时间倒序。

    排序加二级条件 id desc 是必要的：同一秒内问了两个问题，
    时间戳完全相同，只按 created_at 排的话顺序不确定 —— 刷新一下两条就换位置了。
    """
    q = db.query(QaHistory).filter(QaHistory.user_id == user_id)
    if keyword and keyword.strip():
        q = q.filter(QaHistory.question.ilike(f"%{keyword.strip()}%"))

    rows = (
        q.order_by(QaHistory.created_at.desc(), QaHistory.id.desc())
        .offset(max(offset, 0))
        .limit(min(max(limit, 1), MAX_LIMIT))
        .all()
    )
    return [_to_dict(r) for r in rows]


def delete_one(db: Session, user_id: int, history_id: int) -> None:
    """删一条。

    ⚠️ 注意 filter 里带了 user_id —— 这是**越权防护**：
       不能只按 id 查，否则用户 A 猜一个 id 就能删掉用户 B 的历史。
       查不到就报 404（而不是 403）：不告诉对方"这条记录存在，只是不是你的"。
    """
    row = (
        db.query(QaHistory)
        .filter(QaHistory.id == history_id, QaHistory.user_id == user_id)
        .first()
    )
    if row is None:
        raise NotFoundError("记录不存在")

    db.delete(row)
    db.commit()


def clear_mine(db: Session, user_id: int) -> int:
    """清空我的全部历史，返回删掉的条数（前端要显示"已清空 N 条"）。"""
    count = db.query(QaHistory).filter(QaHistory.user_id == user_id).delete()
    db.commit()
    return count


def _to_dict(row: QaHistory) -> dict:
    """ORM -> 前端字典。JSON 文本在这里解成数组（见文件头说明）。"""
    try:
        sources = json.loads(row.sources or "[]")
        if not isinstance(sources, list):
            sources = []
    except (ValueError, TypeError):
        # 库里那串文本坏了（手改过、或者老版本写进去的格式不同）也不能让接口挂掉 ——
        # 一条记录显示不出出处，总比整个历史页打不开好。
        sources = []

    return {
        "id": row.id,
        "question": row.question,
        "answer": row.answer,
        "sources": sources,
        "sourceDoc": row.source_doc,
        "seconds": row.seconds or 0.0,
        "createdAt": fmt(row.created_at),
    }
