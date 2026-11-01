"""ابزار مشترک صفحه‌بندی برای Repositoryهای SQLite (همه Parameterized)."""
from __future__ import annotations

from typing import Callable, Sequence

from repository.interface import Page

MAX_PER_PAGE = 50


def clamp(page: int, per_page: int) -> tuple[int, int]:
    return max(0, int(page)), max(1, min(int(per_page), MAX_PER_PAGE))


def paged(conn, *, columns: str, frm: str, where: str, params: Sequence,
          order: str, page: int, per_page: int, mapper: Callable) -> Page:
    page, per_page = clamp(page, per_page)
    total = conn.execute(f"SELECT COUNT(*) FROM {frm} {where}", tuple(params)).fetchone()[0]
    rows = conn.execute(
        f"SELECT {columns} FROM {frm} {where} ORDER BY {order} LIMIT ? OFFSET ?",
        (*params, per_page, page * per_page),
    ).fetchall()
    return Page(items=[mapper(r) for r in rows], total=total, page=page, per_page=per_page)


def like_escape(q: str) -> str:
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
