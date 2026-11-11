"""日期校验：纯函数，专门处理「视觉模型把生产日期识别成保质期」这类错误。

输出三类信息：
- 修正后的 `production_date` / `expiry_date`
- `warnings`：每条含 code / field / message / before / after，前端逐条展示让用户确认
- `shelf_life_days`：两个日期都有时补算，便于人工核对

规则（顺序执行，全部可回溯）：
1. 两者都有且 生产 > 到期 → 物理上不可能，判定为**互错**，自动交换并告警 `DATE_SWAPPED`；
2. 只有到期日且早于今天 → 告警 `EXPIRY_IN_PAST`（很可能是把生产日期填进了到期日）；
3. 只有生产日 + 保质期天数 → 推算到期日，告警 `EXPIRY_DERIVED`；
4. 两个日期完全相同 → 告警 `SAME_DAY_FILLED`；
5. 生产日早于今天 10 年 / 到期日晚于今天 20 年 → 告警 `DATE_OUT_OF_RANGE`。
"""
from __future__ import annotations

from datetime import date, timedelta

MAX_PAST_DAYS = 3650
MAX_FUTURE_DAYS = 7300


def _w(code: str, field: str, message: str, before=None, after=None) -> dict:
    return {"code": code, "field": field, "message": message, "before": before, "after": after}


def validate_dates(
    *,
    production_date: date | None,
    expiry_date: date | None,
    shelf_life_days: int | None,
    today: date,
) -> tuple[date | None, date | None, int | None, list[dict]]:
    prod, exp = production_date, expiry_date
    warnings: list[dict] = []

    # 1) 互错：生产晚于到期
    if prod and exp and prod > exp:
        original = {"production_date": prod.isoformat(), "expiry_date": exp.isoformat()}
        prod, exp = exp, prod
        warnings.append(
            _w(
                "DATE_SWAPPED",
                "production_date/expiry_date",
                "生产日期晚于到期日期，疑似把两者识别反了，已自动交换，请核对",
                before=original,
                after={"production_date": prod.isoformat(), "expiry_date": exp.isoformat()},
            )
        )

    # 2) 只有到期日却早于今天
    if exp and not prod and exp < today:
        warnings.append(
            _w(
                "EXPIRY_IN_PAST",
                "expiry_date",
                "只识别到到期日且已过期，可能把生产日期识别成了到期日，请补充生产日期",
                before=exp.isoformat(),
            )
        )

    # 3) 由生产日 + 保质期推算到期日
    if prod and not exp and shelf_life_days and shelf_life_days > 0:
        exp = prod + timedelta(days=shelf_life_days)
        warnings.append(
            _w(
                "EXPIRY_DERIVED",
                "expiry_date",
                f"未识别到到期日，按生产日期 + {shelf_life_days} 天推算",
                after=exp.isoformat(),
            )
        )

    # 4) 两处填了同一天
    if prod and exp and prod == exp:
        warnings.append(
            _w(
                "SAME_DAY_FILLED",
                "expiry_date",
                "生产日期与到期日期相同，通常至少应有几天的保质期，请核对",
                after=exp.isoformat(),
            )
        )

    # 5) 超出合理范围
    if prod and (today - prod).days > MAX_PAST_DAYS:
        warnings.append(
            _w("DATE_OUT_OF_RANGE", "production_date", "生产日期早于 10 年前，请核对", before=prod.isoformat())
        )
    if exp and (exp - today).days > MAX_FUTURE_DAYS:
        warnings.append(
            _w("DATE_OUT_OF_RANGE", "expiry_date", "到期日期晚于 20 年后，请核对", before=exp.isoformat())
        )

    # 补算保质期天数
    days = (exp - prod).days if (prod and exp) else shelf_life_days
    return prod, exp, days, warnings


def normalize_barcode(raw: str | None) -> str:
    """条码只保留数字与字母，去掉空格与连字符（扫码枪常带分隔符）。"""
    if not raw:
        return ""
    return "".join(ch for ch in raw if ch.isalnum())
