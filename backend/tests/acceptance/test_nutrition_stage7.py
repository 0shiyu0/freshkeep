"""阶段 7 营养管理验收：项目、档案、换算、快照、日/周期统计、目标、达标率、来源。

用户给定的验收用例（数字不可改）：
  每 100g 鸡胸肉 165kcal / 31g 蛋白 / 3.6g 脂肪，消耗 200g
  → 330 kcal / 62 g / 7.2 g；
  之后把档案蛋白质改成 30g，该笔历史消耗与今日统计**都不得变化**。
"""
from __future__ import annotations

from decimal import Decimal

import pytest


@pytest.fixture()
def chicken(seeded):
    """鸡胸肉：每 100g 含 165kcal / 31g 蛋白 / 3.6g 脂肪，来源手动录入。"""
    from app.db.session import SessionLocal
    from app.models import Unit

    with SessionLocal() as db:
        g = db.query(Unit).filter_by(symbol="g").first()
        gid = str(g.id)
    r = seeded.post("/api/v1/ingredients", json={
        "name": "鸡胸肉",
        "default_weight_unit_id": gid,
        "nutrition": [
            {"code": "calories", "value": "165", "basis_amount": "100", "basis_unit_id": gid,
             "source": "manual"},
            {"code": "protein", "value": "31", "basis_amount": "100", "basis_unit_id": gid,
             "source": "manual"},
            {"code": "fat", "value": "3.6", "basis_amount": "100", "basis_unit_id": gid,
             "source": "packaging_label"},
        ],
    })
    assert r.status_code == 201, r.text
    return {"id": r.json()["data"]["id"], "g_id": gid}


def _batch(client, ing_id: str, weight: str, cost: str) -> dict:
    from datetime import timedelta

    from app.core.time import biz_today

    r = client.post("/api/v1/batches", json={
        "ingredient_id": ing_id, "weight": weight, "purchase_cost": cost,
        "expiry_date": (biz_today() + timedelta(days=10)).isoformat(),
    })
    assert r.status_code == 201, r.text
    return r.json()["data"]["batch"]


def _consume(client, ing_id: str, weight: str) -> dict:
    r = client.post("/api/v1/consumptions", json={"ingredient_id": ing_id, "weight": weight})
    assert r.status_code == 201, r.text
    return r.json()["data"]


def _nutrition(client, period: str = "today") -> dict:
    r = client.get("/api/v1/dashboard/nutrition", params={"period": period})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _by_code(data: dict) -> dict[str, Decimal]:
    return {i["code"]: Decimal(i["actual_value"]) for i in data["items"]}


# ---------------------------------------------------------------- 7.1 项目


def test_nutrition_definitions_cover_six_fields(seeded):
    items = seeded.get("/api/v1/nutrition/definitions").json()["data"]["items"]
    codes = {i["code"] for i in items}
    assert {"calories", "protein", "fat", "carbs", "fiber", "sodium"} <= codes
    # 单位必须齐全，前端直接用
    by = {i["code"]: i for i in items}
    assert by["calories"]["unit"] == "kcal"
    assert by["protein"]["unit"] == "g"


# ---------------------------------------------------------------- 7.2 档案


def test_nutrition_profile_is_versioned(seeded, chicken):
    """改档案不覆盖旧行：旧行 is_current=false，新行 version+1。"""
    from sqlalchemy import text

    from app.db.session import SessionLocal

    r = seeded.put(f"/api/v1/ingredients/{chicken['id']}/nutrition", json={
        "items": [{"code": "protein", "value": "30", "basis_amount": "100",
                   "basis_unit_id": chicken["g_id"], "source": "manual"}],
    })
    assert r.status_code == 200, r.text

    with SessionLocal() as db:
        rows = db.execute(text(
            "select value, version, is_current from ingredient_nutrition "
            "where ingredient_id=:i and nutrition_definition_id in "
            "(select id from nutrition_definitions where code='protein') "
            "order by version"
        ), {"i": chicken["id"]}).all()
    assert len(rows) == 2
    assert Decimal(rows[0][0]) == Decimal("31") and rows[0][2] is False
    assert Decimal(rows[1][0]) == Decimal("30") and rows[1][1] == 2 and rows[1][2] is True


def test_nutrition_profile_keeps_source(seeded, chicken):
    """7.9：来源可标记 manual / packaging_label / database，并落到档案行与快照。"""
    from sqlalchemy import text

    from app.db.session import SessionLocal

    d = seeded.get(f"/api/v1/ingredients/{chicken['id']}").json()["data"]
    fat = next(n for n in d["nutrition"] if n["code"] == "fat")
    assert fat["source"] == "packaging_label"

    # 显式改成包装识别来源
    r = seeded.put(f"/api/v1/ingredients/{chicken['id']}/nutrition", json={
        "items": [{"code": "fat", "value": "3.6", "basis_amount": "100",
                   "basis_unit_id": chicken["g_id"], "source": "database"}],
    })
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        cur = db.execute(text(
            "select source from ingredient_nutrition where ingredient_id=:i and is_current "
            "and nutrition_definition_id in (select id from nutrition_definitions where code='fat')"
        ), {"i": chicken["id"]}).first()
    assert cur[0] == "database"


def test_invalid_source_rejected(seeded, chicken):
    r = seeded.put(f"/api/v1/ingredients/{chicken['id']}/nutrition", json={
        "items": [{"code": "fat", "value": "3.6", "basis_amount": "100",
                   "basis_unit_id": chicken["g_id"], "source": "guess"}],
    })
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------- 7.3 / 7.4 验收


def test_acceptance_200g_linear_conversion(seeded, chicken):
    """用户验收：200g → 330kcal / 62g 蛋白 / 7.2g 脂肪。"""
    _batch(seeded, chicken["id"], "500", "18.00")
    data = _consume(seeded, chicken["id"], "200")

    snap = {n["code"]: Decimal(n["actual_value"]) for n in data["nutrition"]}
    assert snap["calories"] == Decimal("330.0000")
    assert snap["protein"] == Decimal("62.0000")
    assert snap["fat"] == Decimal("7.2000")

    today = _by_code(_nutrition(seeded, "today"))
    assert today["calories"] == Decimal("330.0000")
    assert today["protein"] == Decimal("62.0000")
    assert today["fat"] == Decimal("7.2000")


def test_acceptance_history_survives_profile_change(seeded, chicken):
    """改档案蛋白为 30g 后：历史快照、今日统计都不变；新消耗按新档案算。"""
    _batch(seeded, chicken["id"], "1000", "35.00")
    first = _consume(seeded, chicken["id"], "200")
    cid = first["consumption"]["id"]

    seeded.put(f"/api/v1/ingredients/{chicken['id']}/nutrition", json={
        "items": [{"code": "protein", "value": "30", "basis_amount": "100",
                   "basis_unit_id": chicken["g_id"], "source": "manual"}],
    })

    # 历史快照行不变
    from sqlalchemy import text

    from app.db.session import SessionLocal

    with SessionLocal() as db:
        old = db.execute(text(
            "select actual_value from consumption_nutrition where consumption_id=:c "
            "and nutrition_definition_id in (select id from nutrition_definitions where code='protein')"
        ), {"c": cid}).first()
    assert Decimal(old[0]) == Decimal("62.0000")

    # 今日统计仍按快照：蛋白 62g
    assert _by_code(_nutrition(seeded, "today"))["protein"] == Decimal("62.0000")

    # 新消耗按新档案：200g → 60g
    second = _consume(seeded, chicken["id"], "200")
    assert Decimal({n["code"]: n["actual_value"] for n in second["nutrition"]}["protein"]) == Decimal("60.0000")
    # 累计 122g（62 快照 + 60 新算）
    assert _by_code(_nutrition(seeded, "today"))["protein"] == Decimal("122.0000")


# ---------------------------------------------------------------- 7.5 / 7.6 周期


def test_periods_include_month(seeded, chicken):
    """7.6：today / 3d / week / month 四个周期。"""
    _batch(seeded, chicken["id"], "1000", "35.00")
    _consume(seeded, chicken["id"], "200")

    month = _nutrition(seeded, "month")
    assert month["period"] == "month"
    assert month["days"] >= 0
    assert month["has_records"] is True
    # 本月窗口起点必须是 1 号
    assert month["start_date"].endswith("-01")
    assert _by_code(month)["calories"] == Decimal("330.0000")

    for p in ("today", "3d", "week", "month"):
        d = _nutrition(seeded, p)
        assert d["has_records"] is True
        assert d["disclaimer"]


def test_empty_period_is_not_zero(seeded, chicken):
    """空白天与 0 摄入要区分（沿用 M6 口径）。"""
    d = _nutrition(seeded, "week")
    assert d["has_records"] is False
    assert d["record_count"] == 0
    assert all(Decimal(i["actual_value"]) == 0 for i in d["items"])


# ---------------------------------------------------------------- 7.7 / 7.8 目标与达标率


def test_daily_target_and_achievement(seeded, chicken):
    _batch(seeded, chicken["id"], "1000", "35.00")
    _consume(seeded, chicken["id"], "200")
    seeded.put("/api/v1/nutrition/targets", json={
        "items": [{"code": "calories", "target_value": "2000", "period": "daily"}],
    })

    today = next(i for i in _nutrition(seeded, "today")["items"] if i["code"] == "calories")
    assert Decimal(today["target_value"]) == Decimal("2000")
    assert abs(Decimal(today["achievement"]) - Decimal("0.165")) < Decimal("0.0002")

    # 3 天窗口的目标应是 3 天合计，达成率不能按单日目标算
    three = next(i for i in _nutrition(seeded, "3d")["items"] if i["code"] == "calories")
    assert abs(Decimal(three["achievement"]) - Decimal("0.055")) < Decimal("0.0002")


def test_month_achievement_scales_with_days(seeded, chicken):
    from app.core.time import biz_today

    _batch(seeded, chicken["id"], "1000", "35.00")
    _consume(seeded, chicken["id"], "200")
    seeded.put("/api/v1/nutrition/targets", json={
        "items": [{"code": "calories", "target_value": "2000", "period": "daily"}],
    })

    d = _nutrition(seeded, "month")
    days = d["days"] + 1
    row = next(i for i in d["items"] if i["code"] == "calories")
    expected = Decimal("330") / (Decimal("2000") * days)
    assert abs(Decimal(row["achievement"]) - expected) < Decimal("0.0005")
    # 窗口结束日必须是今天
    assert d["end_date"] == biz_today().isoformat()


def test_target_requires_positive_value(seeded):
    r = seeded.put("/api/v1/nutrition/targets", json={
        "items": [{"code": "calories", "target_value": "0", "period": "daily"}],
    })
    assert r.status_code == 400
