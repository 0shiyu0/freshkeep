"""M4 消耗域验收测试：PRD §7.1 的 9 条用例（数字不可改）。

本层从 `database/002_acceptance_check.sql` 平移而来，但断言的是**真实 HTTP API +
真实 PostgreSQL 事务**，不是 SQL 脚本里的手写 INSERT。

用例清单：
1. 批次成本 300g → 10.80，剩余成本 42.20
2. FEFO A 清零、B 剩 900g
3. 营养快照 300g × 165kcal/100g = 495，且改档案后历史不变
4. 库存不足拒绝且不产生部分流水
5. 同 Idempotency-Key 只产生一笔消耗
6. 并发消耗不超卖
7. 撤销消耗：反向流水 + 恢复余额 + 原记录保留
8. 单位不匹配拒绝（无换算关系 / 双计量不自洽）
9. 批量消耗整批回滚

注意：**不在模块层 import app 下的任何模块**（engine 会在 conftest 切测试库前绑定默认库）。
"""
from __future__ import annotations

import threading
import uuid
from decimal import Decimal

import pytest


@pytest.fixture()
def ingredient_with_nutrition(seeded):
    """鸡胸肉：包/克双计量（每包 250g）+ 165kcal/100g 营养档案。"""
    from decimal import Decimal as D

    from app.db.session import SessionLocal
    from app.models import Ingredient, IngredientNutrition, NutritionDefinition, Unit

    with SessionLocal() as db:
        by_name = {u.name: u for u in db.query(Unit).all()}
        kcal = db.query(NutritionDefinition).filter_by(code="calories").first()
        ing = Ingredient(
            name="鸡胸肉",
            default_quantity_unit_id=by_name["包"].id,
            default_weight_unit_id=by_name["克"].id,
            default_unit_weight=D("250"),
        )
        db.add(ing)
        db.flush()
        if kcal:
            db.add(
                IngredientNutrition(
                    ingredient_id=ing.id,
                    nutrition_definition_id=kcal.id,
                    value=D("165.0000"),
                    basis_amount=D("100.000"),
                    basis_unit_id=by_name["克"].id,
                    source="manual",
                    version=1,
                    is_current=True,
                )
            )
        db.commit()
        return {"id": str(ing.id), "kcal_id": str(kcal.id) if kcal else None,
                "g_id": str(by_name["克"].id), "pack_id": str(by_name["包"].id)}


def _add_batch(client, ing_id: str, weight: str, cost: str, expiry: str | None = None,
              quantity: str = "0") -> dict:
    payload = {"ingredient_id": ing_id, "weight": weight, "purchase_cost": cost}
    if expiry:
        payload["expiry_date"] = expiry
    if quantity != "0":
        payload["quantity"] = quantity
    res = client.post("/api/v1/batches", json=payload)
    assert res.status_code == 201, res.text
    return res.json()["data"]["batch"]


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


def _consume(client, ing_id: str, weight: str, **extra):
    return client.post(
        "/api/v1/consumptions",
        json={"ingredient_id": ing_id, "weight": weight, **extra},
    )


# ---------------------------------------------------------------- 1 批次成本


def test_1_batch_cost(seeded, ingredient_with_nutrition):
    """批次1 500g/18元、批次2 1000g/35元，消耗 300g → 10.80 / 剩余 42.20。"""
    iid = ingredient_with_nutrition["id"]
    b1 = _add_batch(seeded, iid, "500", "18.00", "2026-11-10")
    _add_batch(seeded, iid, "1000", "35.00", "2026-11-20")

    res = _consume(seeded, iid, "300")
    assert res.status_code == 201, res.text
    data = res.json()["data"]
    assert data["consumption"]["cost"] == "10.80"
    assert data["consumption"]["weight"] == "300.000"
    assert data["allocations"][0]["batch_id"] == b1["id"]
    assert data["allocations"][0]["cost_delta"] == "-10.80"

    row = _one(f"select remaining_weight, remaining_cost from batches where id='{b1['id']}'")
    assert Decimal(row[0]) == Decimal("200.000")
    assert Decimal(row[1]) == Decimal("7.20")
    total = _one(f"select sum(remaining_cost) from batches where ingredient_id='{iid}'")
    assert Decimal(total[0]) == Decimal("42.20")

    diffs = _rows("select diff_quantity, diff_weight, diff_cost from v_batch_reconcile")
    assert all(all(Decimal(x) == 0 for x in d) for d in diffs), "对账差异必须为 0"


# ---------------------------------------------------------------- 2 FEFO


def test_2_fefo(seeded, ingredient_with_nutrition):
    """A 500g 到期 11-10、B 1000g 到期 11-20，消耗 600g → A 清零、B 剩 900g。"""
    iid = ingredient_with_nutrition["id"]
    a = _add_batch(seeded, iid, "500", "18.00", "2026-11-10")
    b = _add_batch(seeded, iid, "1000", "35.00", "2026-11-20")

    res = _consume(seeded, iid, "600")
    assert res.status_code == 201, res.text
    assert len(res.json()["data"]["allocations"]) == 2

    ra = _one(f"select remaining_weight, remaining_cost, status from batches where id='{a['id']}'")
    rb = _one(f"select remaining_weight, remaining_cost, status from batches where id='{b['id']}'")
    assert Decimal(ra[0]) == 0 and Decimal(ra[1]) == 0, "A 清零且成本尾差结清为 0"
    assert ra[2] == "depleted"
    assert Decimal(rb[0]) == Decimal("900.000")
    assert rb[2] == "active"


# ---------------------------------------------------------------- 3 营养快照


def test_3_nutrition_snapshot_frozen(seeded, ingredient_with_nutrition):
    """300g × 165kcal/100g = 495；改档案到 170 后历史仍 495，新消耗按 170 算。"""
    iid = ingredient_with_nutrition["id"]
    _add_batch(seeded, iid, "1000", "35.00")

    res = _consume(seeded, iid, "300")
    assert res.status_code == 201, res.text
    snap = res.json()["data"]["nutrition"]
    assert any(n["code"] == "calories" and n["actual_value"] == "495.0000" for n in snap), snap
    cid = res.json()["data"]["consumption"]["id"]
    frozen = _one(
        "select basis_snapshot->>'value' from consumption_nutrition "
        f"where consumption_id='{cid}'"
    )
    assert frozen is not None and Decimal(frozen[0]) == Decimal("165")

    # 改营养档案（历史快照不受影响）
    upd = seeded.put(
        f"/api/v1/ingredients/{iid}/nutrition",
        json={"items": [{"code": "calories", "value": "170",
                         "basis_amount": "100", "basis_unit_id": ingredient_with_nutrition["g_id"]}]},
    )
    assert upd.status_code == 200, upd.text
    hist = _one(f"select actual_value from consumption_nutrition where consumption_id='{cid}'")
    assert Decimal(hist[0]) == Decimal("495.0000")

    res2 = _consume(seeded, iid, "200")
    assert res2.status_code == 201, res2.text
    snap2 = res2.json()["data"]["nutrition"]
    assert any(n["code"] == "calories" and n["actual_value"] == "340.0000" for n in snap2), snap2


# ---------------------------------------------------------------- 4 库存不足


def test_4_insufficient_stock_no_partial(seeded, ingredient_with_nutrition):
    """请求 2000g > 可用 500g → 422，且不产生任何 consume 流水、余额不变。"""
    iid = ingredient_with_nutrition["id"]
    _add_batch(seeded, iid, "500", "18.00")

    res = _consume(seeded, iid, "2000")
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "INSUFFICIENT_STOCK"

    tx = _one("select count(*) from inventory_transactions where type='consume'")
    assert tx[0] == 0
    left = _one(f"select sum(remaining_weight) from batches where ingredient_id='{iid}'")
    assert Decimal(left[0]) == Decimal("500.000")


# ---------------------------------------------------------------- 5 幂等


def test_5_idempotency(seeded, ingredient_with_nutrition):
    """同 Idempotency-Key 重复提交 → 只有一笔消耗、只扣一次库存。"""
    iid = ingredient_with_nutrition["id"]
    _add_batch(seeded, iid, "1000", "35.00")
    key = f"acc-{uuid.uuid4().hex[:8]}"
    r1 = _consume(seeded, iid, "100")
    # 明确带 key 的两次
    r2 = seeded.post("/api/v1/consumptions",
                     headers={"Idempotency-Key": key},
                     json={"ingredient_id": iid, "weight": "100"})
    r3 = seeded.post("/api/v1/consumptions",
                     headers={"Idempotency-Key": key},
                     json={"ingredient_id": iid, "weight": "100"})
    assert r2.status_code == 201 and r3.status_code == 201, (r2.text, r3.text)
    assert r2.json()["data"]["consumption"]["id"] == r3.json()["data"]["consumption"]["id"]

    cnt = _one("select count(*) from consumption_records")[0]
    assert cnt == 2  # r1 一笔 + key 那笔（重放不新增）
    left = _one(f"select sum(remaining_weight) from batches where ingredient_id='{iid}'")
    assert Decimal(left[0]) == Decimal("800.000")


# ---------------------------------------------------------------- 6 并发


def test_6_concurrent_no_oversell(seeded, ingredient_with_nutrition):
    """两个线程同时消耗同一批次 400g（总量 500g）→ 一个成功一个 422，余额不为负。"""
    import httpx

    from app.main import app
    from fastapi.testclient import TestClient

    iid = ingredient_with_nutrition["id"]
    _add_batch(seeded, iid, "500", "18.00")
    cookies = dict(seeded.cookies)

    results: list[int] = []

    def worker():
        c = TestClient(app)
        c.cookies.update(cookies)
        r = c.post("/api/v1/consumptions", json={"ingredient_id": iid, "weight": "400"})
        results.append(r.status_code)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start(); t2.start(); t1.join(timeout=30); t2.join(timeout=30)

    assert sorted(results) == [201, 422], f"并发结果异常：{results}"
    left = _one(f"select remaining_weight from batches where ingredient_id='{iid}'")
    assert Decimal(left[0]) == Decimal("100.000")
    assert Decimal(left[0]) >= 0


# ---------------------------------------------------------------- 7 撤销


def test_7_reverse(seeded, ingredient_with_nutrition):
    """撤销消耗 → 新增 reverse 流水、恢复批次余额、原记录保留且状态 reversed。"""
    iid = ingredient_with_nutrition["id"]
    _add_batch(seeded, iid, "1000", "35.00")
    created = _consume(seeded, iid, "300").json()["data"]["consumption"]

    res = seeded.post(f"/api/v1/consumptions/{created['id']}/reverse", json={"reason": "记错了"})
    assert res.status_code == 201, res.text

    rev = _one("select count(*) from inventory_transactions where type='reverse'")
    assert rev[0] == 1
    left = _one(f"select sum(remaining_weight) from batches where ingredient_id='{iid}'")
    assert Decimal(left[0]) == Decimal("1000.000")
    rec = _one(f"select status, reversed_by_transaction_id from consumption_records where id='{created['id']}'")
    assert rec[0] == "reversed" and rec[1] is not None
    diffs = _rows("select diff_quantity, diff_weight, diff_cost from v_batch_reconcile")
    assert all(all(Decimal(x) == 0 for x in d) for d in diffs)


# ---------------------------------------------------------------- 8 单位


def test_8_unit_mismatch(seeded, ingredient_with_nutrition):
    """无换算关系要求「按数量推算重量」→ 422；双计量不自洽 → 422；
    无换算关系只给数量 → 允许（按数量维度扣减，不推算重量）。"""
    from app.db.session import SessionLocal
    from app.models import Ingredient

    iid = ingredient_with_nutrition["id"]
    _add_batch(seeded, iid, "1000", "35.00")

    # 造一个没有换算关系的食材
    with SessionLocal() as db:
        ing = Ingredient(name="无换算食材")
        db.add(ing); db.commit(); db.refresh(ing)
        plain_id = str(ing.id)
    _add_batch(seeded, plain_id, "0", "10.00", quantity="2")

    # ① 要求自动换算 → 阶段 2 的 /conversion 明确拒绝（PRD §7.1 用例 8）
    r0 = seeded.get(f"/api/v1/ingredients/{plain_id}/conversion", params={"quantity": "2"})
    assert r0.status_code == 422 and r0.json()["error"]["code"] == "UNIT_NOT_CONVERTIBLE", r0.text

    # ② 无换算关系，只给数量 → 按数量维度消耗成功，重量 delta 为 0（不推算）
    r = seeded.post("/api/v1/consumptions",
                    json={"ingredient_id": plain_id, "quantity": "1"})
    assert r.status_code == 201, r.text
    assert r.json()["data"]["consumption"]["weight"] == "0.000"
    assert r.json()["data"]["consumption"]["quantity"] == "1.000"

    # ③ 有换算关系：2 包应为 500g，传 300g 不自洽
    r2 = seeded.post("/api/v1/consumptions",
                     json={"ingredient_id": iid, "quantity": "2", "weight": "300"})
    assert r2.status_code == 422 and r2.json()["error"]["code"] == "INCONSISTENT_MEASURE", r2.text


# ---------------------------------------------------------------- 9 批量回滚


def test_9_batch_all_or_nothing(seeded, ingredient_with_nutrition):
    """批量消耗中一项库存不足 → 整批失败，两个食材余额均保持原值。"""
    iid = ingredient_with_nutrition["id"]
    _add_batch(seeded, iid, "1000", "35.00")
    other = seeded.post("/api/v1/ingredients", json={"name": "牛奶"}).json()["data"]["id"]
    _add_batch(seeded, other, "500", "10.00")

    res = seeded.post("/api/v1/consumptions/batch", json={
        "items": [
            {"ingredient_id": iid, "weight": "100"},
            {"ingredient_id": other, "weight": "9999"},
        ],
    })
    assert res.status_code == 422, res.text
    a = _one(f"select sum(remaining_weight) from batches where ingredient_id='{iid}'")
    b = _one(f"select sum(remaining_weight) from batches where ingredient_id='{other}'")
    assert Decimal(a[0]) == Decimal("1000.000")
    assert Decimal(b[0]) == Decimal("500.000")
    assert _one("select count(*) from consumption_records")[0] == 0
