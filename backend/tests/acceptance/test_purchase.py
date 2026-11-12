"""阶段 3 验收：采购入库与独立批次管理。

对应 6 条验收标准：
1. 同一食材采购两次生成两个独立批次；
2. 不同采购价格分别独立保存；
3. 每个批次可单独设置到期日期；
4. 入库后自动生成库存流水；
5. 重复提交不能重复入库（幂等键）；
6. 禁止出现无来源的库存增加（库存增量必须等于流水增量）。

M3 已交付五步事务与批次 CRUD，本文件同时覆盖阶段 3 新增能力：
入库可填生产/开封日期、跨食材批次列表搜索、批次详情与按批次查流水。
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest


@pytest.fixture()
def ing(seeded):
    """两个食材（走 API 建档，保证拼音可搜）。"""
    from app.db.session import SessionLocal
    from app.models import Unit

    with SessionLocal() as db:
        g = db.query(Unit).filter_by(symbol="g").first()
        gid = str(g.id)
    ids = {}
    for name in ("鸡胸肉", "牛奶"):
        res = seeded.post("/api/v1/ingredients", json={"name": name, "default_weight_unit_id": gid})
        assert res.status_code == 201, res.text
        ids[name] = res.json()["data"]["id"]
    return ids


def _days(n: int) -> str:
    from datetime import timedelta

    from app.core.time import biz_today

    return (biz_today() + timedelta(days=n)).isoformat()


def _one(sql: str):
    from app.db.session import SessionLocal
    from sqlalchemy import text

    with SessionLocal() as db:
        return db.execute(text(sql)).first()


def _purchase(client, ing_id: str, **extra):
    payload = {"ingredient_id": ing_id, **extra}
    return client.post("/api/v1/batches", json=payload)


# ---------------------------------------------------------------- 1 / 2 / 3


def test_two_purchases_create_independent_batches(seeded, ing):
    """同一食材采购两次 → 两个批次，价格各自独立，到期日各自独立。"""
    a = _purchase(seeded, ing["鸡胸肉"], weight="500", purchase_cost="18.00", expiry_date=_days(3))
    b = _purchase(seeded, ing["鸡胸肉"], weight="1000", purchase_cost="40.00", expiry_date=_days(20))
    assert a.status_code == 201 and b.status_code == 201, (a.text, b.text)
    ba, bb = a.json()["data"]["batch"], b.json()["data"]["batch"]

    assert ba["id"] != bb["id"]
    assert ba["batch_no"] != bb["batch_no"]
    assert ba["purchase_cost"] == "18.00" and bb["purchase_cost"] == "40.00"
    assert ba["expiry_date"] != bb["expiry_date"]

    # 单位成本也各自独立：18/500 = 0.0360，40/1000 = 0.0400
    ua = _one(f"select unit_cost from transaction_allocations where batch_id='{ba['id']}'")
    ub = _one(f"select unit_cost from transaction_allocations where batch_id='{bb['id']}'")
    assert Decimal(ua[0]) == Decimal("0.0360")
    assert Decimal(ub[0]) == Decimal("0.0400")

    cnt = _one(f"select count(*) from batches where ingredient_id='{ing['鸡胸肉']}'")
    assert cnt[0] == 2


def test_purchase_stores_all_four_dates(seeded, ing):
    """购买 / 生产 / 到期 / 开封 四个日期都能保存。"""
    res = _purchase(
        seeded, ing["鸡胸肉"], weight="500", purchase_cost="18.00",
        purchase_date=_days(-2), production_date=_days(-5),
        expiry_date=_days(10), opened_date=_days(-1),
    )
    assert res.status_code == 201, res.text
    b = res.json()["data"]["batch"]
    assert b["purchase_date"] == _days(-2)
    assert b["production_date"] == _days(-5)
    assert b["expiry_date"] == _days(10)
    assert b["opened_date"] == _days(-1)


# ---------------------------------------------------------------- 4 / 6


def test_purchase_writes_transaction_and_stock_matches_flow(seeded, ing):
    """入库必写 purchase 流水，且库存总量 == 流水增量之和（无来源库存增加 = 0）。"""
    _purchase(seeded, ing["鸡胸肉"], weight="500", purchase_cost="18.00")
    _purchase(seeded, ing["鸡胸肉"], weight="700", purchase_cost="25.00")

    tx = _one(
        "select count(*), sum(weight_delta) from inventory_transactions "
        f"where type='purchase' and ingredient_id='{ing['鸡胸肉']}'"
    )
    assert tx[0] == 2
    assert Decimal(tx[1]) == Decimal("1200.000")

    stock = _one(
        "select coalesce(sum(remaining_weight),0) from batches "
        f"where ingredient_id='{ing['鸡胸肉']}'"
    )
    flow = _one(
        "select coalesce(sum(weight_delta),0) from inventory_transactions "
        f"where ingredient_id='{ing['鸡胸肉']}'"
    )
    assert Decimal(stock[0]) == Decimal(flow[0]) == Decimal("1200.000")

    diffs = _one(
        f"select count(*) from v_batch_reconcile where ingredient_id='{ing['鸡胸肉']}' "
        "and (diff_quantity<>0 or diff_weight<>0 or diff_cost<>0)"
    )
    assert diffs[0] == 0


# ---------------------------------------------------------------- 5


def test_duplicate_submit_creates_only_one_batch(seeded, ing):
    """同 Idempotency-Key 重复提交 → 只入库一次。"""
    key = f"stage3-{uuid.uuid4().hex[:8]}"
    payload = {"ingredient_id": ing["鸡胸肉"], "weight": "300", "purchase_cost": "9.00"}
    r1 = seeded.post("/api/v1/batches", headers={"Idempotency-Key": key}, json=payload)
    r2 = seeded.post("/api/v1/batches", headers={"Idempotency-Key": key}, json=payload)
    assert r1.status_code == 201 and r2.status_code == 201, (r1.text, r2.text)
    assert r1.json()["data"]["batch"]["id"] == r2.json()["data"]["batch"]["id"]

    cnt = _one(f"select count(*) from batches where ingredient_id='{ing['鸡胸肉']}'")
    assert cnt[0] == 1
    tx = _one(f"select count(*) from inventory_transactions where ingredient_id='{ing['鸡胸肉']}'")
    assert tx[0] == 1


# ---------------------------------------------------------------- 批次列表 / 详情


def test_batch_list_search_by_ingredient_name(seeded, ing):
    """跨食材批次列表：按食材名（中文/拼音）搜索、按状态筛选。"""
    _purchase(seeded, ing["鸡胸肉"], weight="500", purchase_cost="18.00")
    _purchase(seeded, ing["牛奶"], weight="1000", purchase_cost="12.00")

    all_rows = seeded.get("/api/v1/batches", params={"page_size": 50}).json()["data"]
    assert all_rows["total"] >= 2

    zh = seeded.get("/api/v1/batches", params={"q": "鸡胸"}).json()["data"]
    assert zh["total"] == 1 and zh["items"][0]["ingredient_name"] == "鸡胸肉"

    py = seeded.get("/api/v1/batches", params={"q": "jixiong"}).json()["data"]
    assert py["total"] == 1

    active = seeded.get("/api/v1/batches", params={"status": "active"}).json()["data"]
    assert all(i["status"] == "active" for i in active["items"])


def test_batch_detail_has_initial_remaining_and_unit_cost(seeded, ing):
    """批次详情：初始/剩余/成本/单位成本齐备，且可按 batch_id 查该批次流水。"""
    created = _purchase(
        seeded, ing["鸡胸肉"], weight="500", purchase_cost="18.00", expiry_date=_days(5)
    ).json()["data"]["batch"]
    other = _purchase(
        seeded, ing["鸡胸肉"], weight="1000", purchase_cost="40.00", expiry_date=_days(30)
    ).json()["data"]["batch"]

    d = seeded.get(f"/api/v1/batches/{created['id']}").json()["data"]
    assert d["initial_weight"] == "500.000"
    assert d["remaining_weight"] == "500.000"
    assert d["purchase_cost"] == "18.00"
    assert d["remaining_cost"] == "18.00"
    assert d["unit_cost"] == "0.0360"
    assert d["expiry_date"] == _days(5)

    # 只返回影响过该批次的流水（另一个批次的入库不能混进来）
    flow = seeded.get(
        "/api/v1/inventory/transactions", params={"batch_id": created["id"]}
    ).json()["data"]
    assert flow["total"] == 1, flow
    assert flow["items"][0]["type"] == "purchase"
    assert flow["items"][0]["weight_delta"] == "500.000"

    # 报损跨两个批次后，两个批次都能查到自己那条流水
    seeded.post("/api/v1/inventory/spoilage", json={
        "ingredient_id": ing["鸡胸肉"], "weight": "700", "reason": "phase3 测试",
    })
    f1 = seeded.get("/api/v1/inventory/transactions",
                    params={"batch_id": created["id"]}).json()["data"]
    f2 = seeded.get("/api/v1/inventory/transactions",
                    params={"batch_id": other["id"]}).json()["data"]
    assert f1["total"] == 2 and f2["total"] == 2  # 各自 1 条入库 + 同一条报损
    assert any(i["type"] == "spoilage" for i in f1["items"])
    assert any(i["type"] == "spoilage" for i in f2["items"])


def test_batch_detail_404(seeded):
    assert (
        seeded.get(f"/api/v1/batches/{uuid.uuid4()}").status_code == 404
    )
