"""时间工具：数据库存 UTC，业务"哪一天"按 Asia/Shanghai（AGENTS.md §4.6）。

禁止用无时区的 datetime.now()；业务日期边界一律走这里。
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

BIZ_TZ = ZoneInfo("Asia/Shanghai")


def biz_today() -> date:
    """业务意义上的"今天"（Asia/Shanghai）。"""
    return datetime.now(BIZ_TZ).date()


def biz_now() -> datetime:
    """带业务时区的当前时刻（用于展示与日志，不写库）。"""
    return datetime.now(BIZ_TZ)


def days_until(d: date | None) -> int | None:
    """今天距目标日期的天数：明天=1、今天=0、昨天=-1；None 传 None。"""
    if d is None:
        return None
    return (d - biz_today()).days
