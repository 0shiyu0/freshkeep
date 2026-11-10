"""阶段 4 库存引擎验收：8 项必须测试 + 4.1 流水口径库存 + 4.12 对账修复。

8 项必须测试（用户指定，逐条对应）：
1. 消耗 300g 时正确分配批次
2. 库存不足时整笔失败
3. 批量消耗中一项失败则全部回滚
4. 两次并发消耗不出现负库存
5. 撤销消耗通过反向流水恢复
6. 批次归零时剩余成本归零
7. 网络重复提交不重复扣库存
8. 手动调整库存生成调整流水

本文件是阶段 4 的交付证据：每条用例都能独立运行，断言到分/毫克。
"""
from __future__ import annotations

import threading
import uuid
from decimal import Decimal

import pytest


@pytest.fixture()
def ing(seeded):
    """鸡胸肉（克）+ 牛奶（克）两个食材，走 API 建档保证拼音可用。"""
    from app.db.session import SessionLocal
    from app.models import Unit

    with SessionLocal() as db:
        g = db.query(Unit).filter_by(symbol="g").first()
        gid = str(g.id)
    ids = {}
    for name in ("鸡胸肉", "牛奶"):
        r = seeded.post("/api/v1/ingredients", json={"name": name, "default_weight_unit_id": gid})
        assert r.status_code == 201, r.text
        ids[name] = r.json()["data"]["id"]
    return ids


def _days(n: int) -> str:
    from datetime import timedelta

    from app.core.time import biz_today

    return (biz_today() + timedelta(days=n)).isoformat()


def _batch(client, ing_id: str, weight: str, cost: str, expiry_days: int | None = None) -> dict:
    payload = {"ingredient_id": ing_id, "weight": weight, "purchase_cost": cost}
    if expiry_days is not None:
        payload["expiry_date"] = _days(expiry_days)
    r = client.post("/api/v1/batches", json=payload)
    assert r.status_code == 201, r.text
    return r.json()["data"]["batch"]


def _one(sql: str):
    from sqlalchemy import text

    from app.db.session import SessionLocal

    with SessionLocal() as db:
        return db.execute(text(sql)).first()


def _rows(sql: str):
    from sqlalchemy import text

    from app.db.session import SessionLocal

    with SessionLocal() as db:
        return db.execute(text(sql)).all()


def reconcile_diffs(ing_id: str) -> int:
    return _one(
        f"select count(*) from v_batch_reconcile where ingredient_id='{ing_id}' "
        "and (diff_quantity<>0 or diff_weight<>0 or diff_cost<>0)"
    )[0]


# ---------------------------------------------------------------- ① 消耗 300g


def test_1_consume_300g_allocates_correct_batches(seeded, ing):
    iid = ing["鸡胸肉"]
    b1 = _batch(seeded, iid, "500", "18.00", 3)
    b2 = _batch(seeded, iid, "1000", "35.00", 20)

    r = seeded.post("/api/v1/consumptions", json={"ingredient_id": iid, "weight": "300"})
    assert r.status_code == 201, r.text
    data = r.json()["data"]

    assert len(data["allocations"]) == 1
    a = data["allocations"][0]
    assert a["batch_id"] == b1["id"], "应扣到期更早的批次"
    assert a["weight_delta"] == "-300.000"
    assert a["cost_delta"] == "-10.80"
    assert data["consumption"]["cost"] == "10.80"

    ra = _one(f"select remaining_weight, remaining_cost from batches where id='{b1['id']}'")
    rb = _one(f"select remaining_weight, remaining_cost from batches where id='{b2['id']}'")
    assert Decimal(ra[0]) == Decimal("200.000") and Decimal(ra[1]) == Decimal("7.20")
    assert Decimal(rb[0]) == Decimal("1000.000") and Decimal(rb[1]) == Decimal("35.00")
    assert reconcile_diffs(iid) == 0


# ---------------------------------------------------------------- ② 库存不足


def test_2_insufficient_stock_fails_whole_request(seeded, ing):
    iid = ing["鸡胸肉"]
    _batch(seeded, iid, "500", "18.00")
    before = _one(f"select remaining_weight from batches where ingredient_id='{iid}'")

    r = seeded.post("/api/v1/consumptions", json={"ingredient_id": iid, "weight": "600"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INSUFFICIENT_STOCK"
    assert _one("select count(*) from inventory_transactions where type='consume'")[0] == 0
    after = _one(f"select remaining_weight from batches where ingredient_id='{iid}'")
    assert before == after


# ---------------------------------------------------------------- ③ 批量回滚


def test_3_batch_consume_rolls_back_all_on_one_failure(seeded, ing):
    a, b = ing["鸡胸肉"], ing["牛奶"]
    _batch(seeded, a, "1000", "35.00")
    _batch(seeded, b, "500", "12.00")

    r = seeded.post("/api/v1/consumptions/batch", json={"items": [
        {"ingredient_id": a, "weight": "100"},
        {"ingredient_id": b, "weight": "9999"},
    ]})
    assert r.status_code == 422, r.text
    assert _one("select count(*) from consumption_records")[0] == 0
    assert _one(f"select sum(remaining_weight) from batches where ingredient_id='{a}'")[0] == Decimal("1000.000")
    assert _one(f"select sum(remaining_weight) from batches where ingredient_id='{b}'")[0] == Decimal("500.000")


# ---------------------------------------------------------------- ④ 并发不超卖


def test_4_concurrent_consumption_no_negative_stock(seeded, ing):
    from fastapi.testclient import TestClient

    from app.main import app

    iid = ing["鸡胸肉"]
    _batch(seeded, iid, "500", "18.00")
    cookies = dict(seeded.cookies)
    codes: list[int] = []

    def worker():
        c = TestClient(app)
        c.cookies.update(cookies)
        codes.append(c.post("/api/v1/consumptions",
                            json={"ingredient_id": iid, "weight": "400"}).status_code)

    ts = [threading.Thread(target=worker) for _ in range(2)]
    for t in ts: t.start()
    for t in ts: t.join(timeout=30)

    assert sorted(codes) == [201, 422], codes
    left = _one(f"select remaining_weight from batches where ingredient_id='{iid}'")[0]
    assert Decimal(left) == Decimal("100.000")
    assert Decimal(left) >= 0
    assert reconcile_diffs(iid) == 0


# ---------------------------------------------------------------- ⑤ 撤销


def test_5_reverse_restores_stock_via_opposite_flow(seeded, ing):
    iid = ing["鸡胸肉"]
    _batch(seeded, iid, "1000", "35.00")
    cid = seeded.post("/api/v1/consumptions",
                      json={"ingredient_id": iid, "weight": "300"}).json()["data"]["consumption"]["id"]

    r = seeded.post(f"/api/v1/consumptions/{cid}/reverse", json={"reason": "阶段4 撤销"})
    assert r.status_code == 201, r.text

    types = [row[0] for row in _rows(
        f"select type from inventory_transactions where ingredient_id='{iid}' order by created_at"
    )]
    assert types == ["purchase", "consume", "reverse"]
    assert _one(f"select sum(remaining_weight) from batches where ingredient_id='{iid}'")[0] == Decimal("1000.000")
    rec = _one(f"select status, reversed_by_transaction_id from consumption_records where id='{cid}'")
    assert rec[0] == "reversed" and rec[1] is not None
    assert reconcile_diffs(iid) == 0


# ---------------------------------------------------------------- ⑥ 归零尾差


def test_6_zeroed_batch_has_zero_remaining_cost(seeded, ing):
    iid = ing["鸡胸肉"]
    # 成本 10.00 / 300g = 0.0333…，整批扣完必须正好剩 0 而不是 0.01
    b = _batch(seeded, iid, "300", "10.00")
    r = seeded.post("/api/v1/consumptions", json={"ingredient_id": iid, "weight": "300"})
    assert r.status_code == 201, r.text
    row = _one(f"select remaining_weight, remaining_cost, status from batches where id='{b['id']}'")
    assert Decimal(row[0]) == 0
    assert Decimal(row[1]) == 0
    assert row[2] == "depleted"
    assert r.json()["data"]["consumption"]["cost"] == "10.00"
    assert reconcile_diffs(iid) == 0


# ---------------------------------------------------------------- ⑦ 幂等


def test_7_duplicate_network_retry_does_not_double_deduct(seeded, ing):
    iid = ing["鸡胸肉"]
    _batch(seeded, iid, "1000", "35.00")
    key = f"stage4-{uuid.uuid4().hex[:8]}"
    payload = {"ingredient_id": iid, "weight": "100"}

    r1 = seeded.post("/api/v1/consumptions", headers={"Idempotency-Key": key}, json=payload)
    r2 = seeded.post("/api/v1/consumptions", headers={"Idempotency-Key": key}, json=payload)
    r3 = seeded.post("/api/v1/consumptions", headers={"Idempotency-Key": key}, json=payload)

    ids = {r1.json()["data"]["consumption"]["id"], r2.json()["data"]["consumption"]["id"],
           r3.json()["data"]["consumption"]["id"]}
    assert len(ids) == 1
    assert _one("select count(*) from consumption_records")[0] == 1
    assert _one(f"select sum(remaining_weight) from batches where ingredient_id='{iid}'")[0] == Decimal("900.000")
    assert reconcile_diffs(iid) == 0


# ---------------------------------------------------------------- ⑧ 手动调整


def test_8_manual_adjustment_writes_adjustment_flow(seeded, ing):
    iid = ing["鸡胸肉"]
    b = _batch(seeded, iid, "500", "18.00")

    r = seeded.post("/api/v1/inventory/adjustments", json={
        "batch_id": b["id"], "actual_weight": "480", "reason": "阶段4 盘点",
    })
    assert r.status_code == 201, r.text
    tx = _one(
        f"select type, weight_delta, cost_delta, reason from inventory_transactions "
        f"where related_object_id='{b['id']}' and type='adjustment'"
    )
    assert tx is not None and tx[0] == "adjustment"
    assert Decimal(tx[1]) == Decimal("-20.000")
    assert Decimal(tx[2]) == Decimal("-0.72")
    assert tx[3] == "阶段4 盘点"
    assert reconcile_diffs(iid) == 0


# ---------------------------------------------------------------- 4.1 流水口径库存


def test_4_1_ledger_stock_matches_cached(seeded, ing):
    """4.1：按流水重算的库存必须与批次缓存一致。"""
    iid = ing["鸡胸肉"]
    _batch(seeded, iid, "500", "18.00", 3)
    _batch(seeded, iid, "1000", "35.00", 20)
    seeded.post("/api/v1/consumptions", json={"ingredient_id": iid, "weight": "300"})

    res = seeded.get("/api/v1/inventory/ledger-stock")
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    row = next(i for i in data["items"] if i["ingredient_id"] == iid)
    assert row["ledger_weight"] == "1200.000"     # 1500 - 300
    assert row["cached_weight"] == "1200.000"
    assert row["consistency"] == "ok"
    assert row["ledger_cost"] == "42.20"
    assert data["inconsistent_count"] == 0


# ---------------------------------------------------------------- 4.12 对账


def test_4_12_reconcile_detects_and_repairs_cache_drift(seeded, ing):
    """4.12：绕过流水篡改缓存后，对账能发现并按流水修复，且写审计。"""
    from sqlalchemy import text

    from app.db.session import SessionLocal

    iid = ing["鸡胸肉"]
    b = _batch(seeded, iid, "500", "18.00")

    # 人为制造差异：直接改缓存（改小 5g，不违反 remaining <= initial），不写流水
    with SessionLocal() as db:
        db.execute(text("update batches set remaining_weight = remaining_weight - 5 where id=:i"),
                   {"i": b["id"]})
        db.commit()

    r = seeded.get("/api/v1/inventory/reconcile")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    row = next(i for i in data["items"] if i["batch_id"] == b["id"])
    assert row["diff_weight"] == "-5.000"
    assert row["cached_weight"] == "495.000"
    assert row["allocated_weight"] == "500.000"

    fix = seeded.post("/api/v1/inventory/reconcile/repair", json={"batch_ids": [b["id"]]})
    assert fix.status_code == 200, fix.text
    assert fix.json()["data"]["repaired"] == 1

    after = _one(f"select remaining_weight from batches where id='{b['id']}'")
    assert Decimal(after[0]) == Decimal("500.000")
    audit = _one("select count(*) from audit_logs where action='reconcile_repair'")
    assert audit[0] >= 1
    assert reconcile_diffs(iid) == 0

    # 修复后再对账应为空
    again = seeded.get("/api/v1/inventory/reconcile").json()["data"]
    assert all(i["batch_id"] != b["id"] for i in again["items"])
