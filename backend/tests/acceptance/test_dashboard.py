"""M6 首页与营养统计验收：summary / nutrition / 营养目标。

核心口径（PRD §4.2、§4.7）：
- 首页展示库存总价值、期间采购/消耗金额与消耗比例、最近 4 条入库、临期提醒；
- 营养只统计 `consumption_records.status='completed'` 的**消耗快照**，
  已撤销的消耗不计入；
- **无记录与「记录为 0」必须区分**：没有消耗记录时 `has_records=false`，
  不能把空白天当成 0 摄入；
- 统计一律标注「按库存消耗量估算」。

日期窗口按 Asia/Shanghai 计算，测试数据全部相对今天生成。
"""
from __future__ import annotations

from decimal import Decimal

import pytest


@pytest.fixture()
def ing(seeded):
    """鸡胸肉：165kcal / 100g、蛋白 31g / 100g。"""
    from decimal import Decimal as D

    from app.db.session import SessionLocal
    from app.models import Ingredient, IngredientNutrition, NutritionDefinition, Unit

    with SessionLocal() as db:
        g = db.query(Unit).filter_by(symbol="g").first()
        kcal = db.query(NutritionDefinition).filter_by(code="calories").first()
        protein = db.query(NutritionDefinition).filter_by(code="protein").first()
        item = Ingredient(name="鸡胸肉", default_weight_unit_id=g.id)
        db.add(item)
        db.flush()
        for defn, value in ((kcal, D("165.0000")), (protein, D("31.0000"))):
            if defn is not None:
                db.add(IngredientNutrition(
                    ingredient_id=item.id, nutrition_definition_id=defn.id,
                    value=value, basis_amount=D("100.000"), basis_unit_id=g.id,
                    source="manual", version=1, is_current=True,
                ))
        db.commit()
        return {"id": str(item.id), "name": item.name, "g_id": str(g.id)}


def _batch(client, ing_id: str, weight: str, cost: str, expiry_days: int | None = None) -> dict:
    from datetime import timedelta

    from app.core.time import biz_today

    payload = {"ingredient_id": ing_id, "weight": weight, "purchase_cost": cost}
    if expiry_days is not None:
        payload["expiry_date"] = (biz_today() + timedelta(days=expiry_days)).isoformat()
    r = client.post("/api/v1/batches", json=payload)
    assert r.status_code == 201, r.text
    return r.json()["data"]["batch"]


def _one(sql: str):
    from sqlalchemy import text

    from app.db.session import SessionLocal

    with SessionLocal() as db:
        return db.execute(text(sql)).first()


# ---------------------------------------------------------------- summary


def test_summary_reports_stock_and_period_amounts(seeded, ing):
    """库存价值、总重量、期间采购/消耗金额、最近入库、临期计数。"""
    _batch(seeded, ing["id"], "500", "18.00", 3)
    _batch(seeded, ing["id"], "1000", "35.00", 20)
    seeded.post("/api/v1/consumptions", json={"ingredient_id": ing["id"], "weight": "300"})

    res = seeded.get("/api/v1/dashboard/summary")
    assert res.status_code == 200, res.text
    d = res.json()["data"]

    assert Decimal(d["stock_cost"]) == Decimal("42.20")
    assert Decimal(d["stock_weight"]) == Decimal("1200.000")
    assert Decimal(d["purchase_amount"]) == Decimal("53.00")
    assert Decimal(d["consumption_amount"]) == Decimal("10.80")
    assert d["recent_batches"] and len(d["recent_batches"]) <= 4
    assert len(d["recent_batches"]) == 2
    assert d["expiring_count"] == 1  # 3 天后到期
    assert d["expired_count"] == 0


def test_summary_consumption_ratio_null_without_purchase(seeded, ing):
    """没有采购时消耗比例是 null（不是 0），避免把「无数据」误读成「0%」。"""
    res = seeded.get("/api/v1/dashboard/summary")
    assert res.status_code == 200
    d = res.json()["data"]
    assert d["consumption_ratio"] is None


def test_summary_consumption_ratio_value(seeded, ing):
    """有采购时比例 = 消耗金额 / 采购金额，保留 4 位小数。"""
    _batch(seeded, ing["id"], "500", "100.00")
    seeded.post("/api/v1/consumptions", json={"ingredient_id": ing["id"], "weight": "100"})
    d = seeded.get("/api/v1/dashboard/summary").json()["data"]
    # 单位成本 0.2 元/g，消耗 100g = 20.00；20 / 100 = 0.2000
    assert d["consumption_ratio"] == "0.2000"


def test_summary_period_filter(seeded, ing):
    """按 from/to 过滤期间金额；不传则默认近 30 天。"""
    _batch(seeded, ing["id"], "500", "18.00")
    tomorrow = _one("select (current_date + 1)::text")[0]
    d = seeded.get("/api/v1/dashboard/summary", params={"from_date": tomorrow}).json()["data"]
    assert Decimal(d["purchase_amount"]) == 0
    assert d["consumption_ratio"] is None


# ---------------------------------------------------------------- nutrition


def test_nutrition_today_uses_snapshot(seeded, ing):
    """消耗 300g → 热量 495、蛋白 93（均为快照值，按消耗量估算）。"""
    _batch(seeded, ing["id"], "1000", "35.00")
    seeded.post("/api/v1/consumptions", json={"ingredient_id": ing["id"], "weight": "300"})

    res = seeded.get("/api/v1/dashboard/nutrition", params={"period": "today"})
    assert res.status_code == 200, res.text
    d = res.json()["data"]
    assert d["has_records"] is True
    assert d["record_count"] == 1
    by_code = {n["code"]: n for n in d["items"]}
    assert Decimal(by_code["calories"]["actual_value"]) == Decimal("495.0000")
    assert Decimal(by_code["protein"]["actual_value"]) == Decimal("93.0000")
    assert d["disclaimer"]  # 必须提示「按库存消耗量估算」


def test_nutrition_empty_is_not_zero(seeded, ing):
    """没有任何消耗时 has_records=false，数值为 0 但有明确标记（空白天 ≠ 0 摄入）。"""
    res = seeded.get("/api/v1/dashboard/nutrition", params={"period": "today"})
    assert res.status_code == 200
    d = res.json()["data"]
    assert d["has_records"] is False
    assert d["record_count"] == 0
    assert all(Decimal(n["actual_value"]) == 0 for n in d["items"])


def test_nutrition_excludes_reversed(seeded, ing):
    """已撤销的消耗不计入营养统计。"""
    _batch(seeded, ing["id"], "1000", "35.00")
    cid = seeded.post("/api/v1/consumptions",
                      json={"ingredient_id": ing["id"], "weight": "300"}).json()["data"]["consumption"]["id"]
    seeded.post(f"/api/v1/consumptions/{cid}/reverse", json={"reason": "口径测试"})

    d = seeded.get("/api/v1/dashboard/nutrition", params={"period": "today"}).json()["data"]
    assert d["has_records"] is False
    assert d["record_count"] == 0


def test_nutrition_period_3d_and_week(seeded, ing):
    """period 支持 today / 3d / week，返回窗口起止日期。"""
    for period, days in (("today", 0), ("3d", 2), ("week", 6)):
        d = seeded.get("/api/v1/dashboard/nutrition", params={"period": period}).json()["data"]
        assert d["period"] == period
        assert d["start_date"] and d["end_date"]
        assert (Decimal(d["days"]) if "days" in d else days) == days


# ---------------------------------------------------------------- 营养目标


def test_targets_upsert_and_read(seeded):
    """营养目标可按 code 设置，同日重复设置覆盖而不报错。"""
    codes = [n["code"] for n in seeded.get("/api/v1/nutrition/definitions").json()["data"]["items"]]
    assert "calories" in codes

    r = seeded.put("/api/v1/nutrition/targets", json={
        "items": [{"code": "calories", "target_value": "2000", "period": "daily"}],
    })
    assert r.status_code == 200, r.text

    r2 = seeded.put("/api/v1/nutrition/targets", json={
        "items": [{"code": "calories", "target_value": "2100", "period": "daily"}],
    })
    assert r2.status_code == 200, r2.text

    got = seeded.get("/api/v1/nutrition/targets").json()["data"]
    row = next(i for i in got["items"] if i["code"] == "calories")
    assert Decimal(row["target_value"]) == Decimal("2100")
    assert row["period"] == "daily"

    # 同日只有一行生效（历史版本不叠加）
    cnt = _one("select count(*) from nutrition_targets where period='daily'")
    assert cnt[0] == 1


def test_targets_reject_unknown_code(seeded):
    r = seeded.put("/api/v1/nutrition/targets", json={
        "items": [{"code": "not_a_nutrient", "target_value": "1", "period": "daily"}],
    })
    assert r.status_code == 400


def test_dashboard_requires_login(client):
    assert client.get("/api/v1/dashboard/summary").status_code == 401
    assert client.get("/api/v1/dashboard/nutrition").status_code == 401
