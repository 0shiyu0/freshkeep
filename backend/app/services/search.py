"""拼音与搜索辅助。

搜索策略（阶段 2 §2.7）：
- 中文模糊：`name ILIKE %q%`（命中 pg_trgm GIN 索引）
- 全拼：`name_pinyin ILIKE %q%`（niurou / rou）
- 首字母：`name_initials ILIKE %q%`（nr）
- 三者 OR 组合，任一命中即返回；结果按「完全匹配 > 前缀 > 包含」排序

拼音列在写入时由本模块生成并存库，查询时不实时转换（避免每行都算一遍）。
"""
from __future__ import annotations

from pypinyin import Style, lazy_pinyin
from sqlalchemy import case, func, or_
from sqlalchemy.sql import ColumnElement


def to_pinyin(name: str) -> tuple[str, str]:
    """返回 (全拼, 首字母)，都用小写、无分隔符。

    >>> to_pinyin("鸡胸肉")
    ('jixiongrou', 'jxr')
    """
    cleaned = (name or "").strip()
    if not cleaned:
        return "", ""
    full = "".join(lazy_pinyin(cleaned, style=Style.NORMAL, errors="default")).lower()
    initials = "".join(lazy_pinyin(cleaned, style=Style.FIRST_LETTER, errors="default")).lower()
    # 只保留字母数字，避免空格与符号进入索引
    full = "".join(ch for ch in full if ch.isalnum())
    initials = "".join(ch for ch in initials if ch.isalnum())
    return full, initials


def search_filter(name_col, pinyin_col, initials_col, q: str) -> ColumnElement[bool]:
    """构造中文/全拼/首字母三路 OR 条件。q 已转小写并去空格。"""
    pattern = f"%{q}%"
    return or_(
        name_col.ilike(pattern),
        pinyin_col.ilike(pattern),
        initials_col.ilike(pattern),
    )


def relevance_order(name_col, pinyin_col, q: str):
    """完全匹配 0、前缀 1、包含 2，越小越靠前。"""
    return case(
        (func.lower(name_col) == q, 0),
        (name_col.ilike(f"{q}%"), 1),
        (pinyin_col.ilike(f"{q}%"), 2),
        else_=3,
    )
