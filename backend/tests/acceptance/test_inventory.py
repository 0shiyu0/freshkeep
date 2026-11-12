"""M5 库存域测试：库存聚合、流水查询、盘点调整、批量盘点、报损。

核心断言（AGENTS.md §4.2 / PRD §4.6、§7.2）：
- 盘点与报损同样走「流水 + 分配 + 批次缓存 + 一致性断言」，不允许直接改余额；
- 盘盈按批次当前单位成本计入，盘亏按单位成本扣减（扣完取剩余成本结清尾差）；
- 报损按 FEFO 扣批次；
- 批量盘点任一项非法 → 整批回滚；
- 所有操作后 `v_batch_reconcile` 三个 diff 必须为 0。

日期一律相对今天计算（绝对日期会让用例次日失效）。
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest


@pytest.fixture()
def ing(seeded):
    """鸡胸肉：克为重量单位，无数量换算。

    必须走 API 建档：拼音/首字母由服务端生成，直接 ORM 插入不会写这两列，
    会让拼音搜索用例假失败。
    """
    from app.db.session import SessionLocal
    from app.models import Unit

    with SessionLocal() as db:
        g = db.query(Unit).filter_by(symbol="g").first()
        gid = str(g.id)
    res = seeded.post(
        "/api/v1/ingredients", json={"name": "鸡胸肉", "default_weight_unit_id": gid}
    )
    assert res.status_code == 201, res.text
    return {"id": res.json()["data"]["id"], "name": "鸡胸肉"}


def _add_batch(client, ing_id: str, weight: str, cost: str, expiry_days: int | None = None) -> dict:
    from datetime import timedelta

    from app.core.time import biz_today

    payload = {"ingredient_id": ing_id, "weight": weight, "purchase_cost": cost}
    if expiry_days is not None:
        payload["expiry_date"] = (biz_today() + timedelta(days=expiry_days)).isoformat()
    res = client.post("/api/v1/batches", json=payload)
    assert res.status_code == 201, res.text
    return res.json()["data"]["batch"]


def _one(sql: str):
    from app.db.session import SessionLocal
    from sqlalchemy import text

    with SessionLocal() as db:
        return db.execute(text(sql)).first()


def _rows(sql: str):
    from app.db.session import SessionLocal
    from sqlalchemy import text

    with SessionLocal() as db:
        return db.execute(text(sql)).all()


def _diffs_zero() -> bool:
    rows = _rows("select diff_quantity, diff_weight, diff_cost from v_batch_reconcile")
    return all(all(Decimal(x) == 0 for x in r) for r in rows)


# ---------------------------------------------------------------- 库存查询


def test_inventory_list_aggregates(seeded, ing):
    """v_inventory 聚合：总重量、总成本、批次数、最近到期。"""
    _add_batch(seeded, ing["id"], "500", "18.00", expiry_days=2)
    _add_batch(seeded, ing["id"], "1000", "35.00", expiry_days=10)

    res = seeded.get("/api/v1/inventory")
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    row = next(i for i in data["items"] if i["ingredient_id"] == ing["id"])
    assert row["total_weight"] == "1500.000"
    assert row["total_cost"] == "53.00"
    assert row["batch_count"] == 2
    assert row["nearest_expiry"] is not None
    assert row["is_low_stock"] is False
    assert data["total"] >= 1


def test_inventory_low_stock_filter(seeded, ing):
    """低于最低库存的食材能被筛出。"""
    from app.db.session import SessionLocal
    from app.models import Ingredient

    with SessionLocal() as db:
        item = db.get(Ingredient, uuid.UUID(ing["id"]))
        item.minimum_weight = Decimal("1000")
        db.commit()
    _add_batch(seeded, ing["id"], "200", "7.00")

    res = seeded.get("/api/v1/inventory", params={"is_low_stock": "true"})
    assert res.status_code == 200
    ids = [i["ingredient_id"] for i in res.json()["data"]["items"]]
    assert ing["id"] in ids


def test_inventory_search_and_category(seeded, ing):
    """中文与拼音搜索、分类筛选走同一套条件。"""
    _add_batch(seeded, ing["id"], "100", "3.00")
    r1 = seeded.get("/api/v1/inventory", params={"q": "鸡"})
    r2 = seeded.get("/api/v1/inventory", params={"q": "jixiong"})
    assert any(i["ingredient_id"] == ing["id"] for i in r1.json()["data"]["items"])
    assert any(i["ingredient_id"] == ing["id"] for i in r2.json()["data"]["items"])
    r3 = seeded.get("/api/v1/inventory", params={"q": "牛肉"})
    assert all(i["ingredient_id"] != ing["id"] for i in r3.json()["data"]["items"])


def test_inventory_summary(seeded, ing):
    """汇总：总重量、总成本、食材数、临期数（7 天内）。"""
    _add_batch(seeded, ing["id"], "500", "18.00", expiry_days=3)
    res = seeded.get("/api/v1/inventory/summary")
    assert res.status_code == 200, res.text
    d = res.json()["data"]
    assert Decimal(d["total_weight"]) >= Decimal("500")
    assert Decimal(d["total_cost"]) >= Decimal("18.00")
    assert d["ingredient_count"] >= 1
    assert d["expiring_count"] >= 1


def test_transactions_list_and_filter(seeded, ing):
    """入库与消耗都应出现在流水里，可按类型过滤。"""
    _add_batch(seeded, ing["id"], "500", "18.00")
    c = seeded.post("/api/v1/consumptions", json={"ingredient_id": ing["id"], "weight": "100"})
    assert c.status_code == 201, c.text

    all_rows = seeded.get("/api/v1/inventory/transactions").json()["data"]
    types = {t["type"] for t in all_rows["items"]}
    assert {"purchase", "consume"} <= types

    only_consume = seeded.get("/api/v1/inventory/transactions", params={"type": "consume"}).json()["data"]
    assert only_consume["total"] == 1
    assert only_consume["items"][0]["type"] == "consume"


# ---------------------------------------------------------------- 盘点


def test_adjustment_decrease(seeded, ing):
    """盘亏：500g 实际 480g → -20g，成本按单位成本扣减，余额与对账一致。"""
    b = _add_batch(seeded, ing["id"], "500", "18.00")
    res = seeded.post("/api/v1/inventory/adjustments", json={
        "batch_id": b["id"], "actual_weight": "480", "reason": "化冻失水",
    })
    assert res.status_code == 201, res.text
    data = res.json()["data"]
    assert data["weight_delta"] == "-20.000"
    assert data["cost_delta"] == "-0.72"  # 20 × 0.036
    row = _one(f"select remaining_weight, remaining_cost from batches where id='{b['id']}'")
    assert Decimal(row[0]) == Decimal("480.000")
    assert Decimal(row[1]) == Decimal("17.28")
    tx = _one(f"select type from inventory_transactions where id='{data['transaction_id']}'")
    assert tx[0] == "adjustment"
    assert _diffs_zero()


def test_adjustment_increase(seeded, ing):
    """盘盈：500g 实际 520g → +20g，按批次当前单位成本计入。"""
    b = _add_batch(seeded, ing["id"], "500", "18.00")
    res = seeded.post("/api/v1/inventory/adjustments", json={
        "batch_id": b["id"], "actual_weight": "520", "reason": "称重误差",
    })
    assert res.status_code == 201, res.text
    data = res.json()["data"]
    assert data["weight_delta"] == "20.000"
    assert data["cost_delta"] == "0.72"
    row = _one(f"select remaining_weight, remaining_cost from batches where id='{b['id']}'")
    assert Decimal(row[0]) == Decimal("520.000")
    assert Decimal(row[1]) == Decimal("18.72")
    assert _diffs_zero()


def test_adjustment_to_zero_clears_cost(seeded, ing):
    """盘点为 0 → 成本尾差结清为 0，批次状态变 depleted。"""
    b = _add_batch(seeded, ing["id"], "500", "18.00")
    res = seeded.post("/api/v1/inventory/adjustments", json={
        "batch_id": b["id"], "actual_weight": "0", "reason": "全部丢弃",
    })
    assert res.status_code == 201, res.text
    row = _one(f"select remaining_weight, remaining_cost, status from batches where id='{b['id']}'")
    assert Decimal(row[0]) == 0
    assert Decimal(row[1]) == 0
    assert row[2] == "depleted"
    assert _diffs_zero()


def test_adjustment_requires_reason_and_known_batch(seeded, ing):
    b = _add_batch(seeded, ing["id"], "500", "18.00")
    r1 = seeded.post("/api/v1/inventory/adjustments", json={"batch_id": b["id"], "actual_weight": "480"})
    assert r1.status_code == 400, "盘点必须给出原因"
    r2 = seeded.post("/api/v1/inventory/adjustments", json={
        "batch_id": "00000000-0000-0000-0000-000000000000",
        "actual_weight": "100", "reason": "x",
    })
    assert r2.status_code == 404


def test_stocktake_all_or_nothing(seeded, ing):
    """批量盘点中一项非法 → 整批回滚，两个批次余额都不变。"""
    a = _add_batch(seeded, ing["id"], "500", "18.00")
    b = _add_batch(seeded, ing["id"], "1000", "35.00")
    res = seeded.post("/api/v1/inventory/stocktake", json={"items": [
        {"batch_id": a["id"], "actual_weight": "480"},
        {"batch_id": b["id"], "actual_weight": "-5"},
    ]})
    assert res.status_code in (400, 422), res.text
    ra = _one(f"select remaining_weight from batches where id='{a['id']}'")
    rb = _one(f"select remaining_weight from batches where id='{b['id']}'")
    assert Decimal(ra[0]) == Decimal("500.000")
    assert Decimal(rb[0]) == Decimal("1000.000")


def test_stocktake_success(seeded, ing):
    """批量盘点两项都合法 → 都生效，对账为 0。"""
    a = _add_batch(seeded, ing["id"], "500", "18.00")
    b = _add_batch(seeded, ing["id"], "1000", "35.00")
    res = seeded.post("/api/v1/inventory/stocktake", json={"items": [
        {"batch_id": a["id"], "actual_weight": "480", "reason": "盘点"},
        {"batch_id": b["id"], "actual_weight": "990", "reason": "盘点"},
    ]})
    assert res.status_code == 201, res.text
    assert len(res.json()["data"]["items"]) == 2
    assert _diffs_zero()


# ---------------------------------------------------------------- 报损


def test_spoilage_fefo(seeded, ing):
    """报损 600g：A(500, 早到期) 清零、B 剩 900g，写 spoilage 流水。"""
    a = _add_batch(seeded, ing["id"], "500", "18.00", expiry_days=1)
    b = _add_batch(seeded, ing["id"], "1000", "35.00", expiry_days=11)
    res = seeded.post("/api/v1/inventory/spoilage", json={
        "ingredient_id": ing["id"], "weight": "600", "reason": "变质",
    })
    assert res.status_code == 201, res.text
    ra = _one(f"select remaining_weight, status from batches where id='{a['id']}'")
    rb = _one(f"select remaining_weight from batches where id='{b['id']}'")
    assert Decimal(ra[0]) == 0 and ra[1] == "depleted"
    assert Decimal(rb[0]) == Decimal("900.000")
    tx = _one("select type from inventory_transactions where type='spoilage'")
    assert tx is not None
    assert _diffs_zero()


def test_spoilage_rejects_insufficient_and_empty_reason(seeded, ing):
    _add_batch(seeded, ing["id"], "100", "3.60")
    r1 = seeded.post("/api/v1/inventory/spoilage", json={
        "ingredient_id": ing["id"], "weight": "999", "reason": "变质",
    })
    assert r1.status_code == 422 and r1.json()["error"]["code"] == "INSUFFICIENT_STOCK"
    r2 = seeded.post("/api/v1/inventory/spoilage", json={"ingredient_id": ing["id"], "weight": "10"})
    assert r2.status_code == 400, "报损必须给出原因"


def test_inventory_requires_login(client):
    assert client.get("/api/v1/inventory").status_code == 401
    assert client.get("/api/v1/inventory/summary").status_code == 401
