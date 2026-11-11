"""阶段 6 统计验收：金额一致性、时间筛选、粒度、分类占比、排行、周转、撤销。

口径约定（写死在断言里）：
1. 采购/消耗金额一律来自流水聚合（`purchase` / `consume`），与库存价值互不替代；
2. 库存价值 = `Σ batches.remaining_cost`（剩余成本），**不等于**采购总额；
3. 撤销消耗会写 `reverse` 流水，消耗净额随之减少（不需额外过滤 status）；
4. 分类占比按**消耗成本**分组，采购与消耗不重复计入同一维度；
5. 时间窗口按 Asia/Shanghai 自然日，含首日、不含结束日的次日。
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest


@pytest.fixture()
def env(seeded):
    """两个分类（肉类/蔬菜）+ 三个食材。"""
    from app.db.session import SessionLocal
    from app.models import Category, Ingredient, Unit

    with SessionLocal() as db:
        g = db.query(Unit).filter_by(symbol="g").first()
        gid = str(g.id)
        cats = {}
        for name in ("肉类", "蔬菜"):
            cat = db.query(Category).filter_by(name=name, parent_id=None).first()
            if cat is None:
                cat = Category(name=name)
                db.add(cat)
                db.flush()
            cats[name] = str(cat.id)
        db.commit()

    def make(name: str, cat: str) -> str:
        r = seeded.post("/api/v1/ingredients", json={
            "name": name, "default_weight_unit_id": gid, "category_id": cats[cat],
        })
        assert r.status_code == 201, r.text
        return r.json()["data"]["id"]

    return {
        "g_id": gid,
        "cats": cats,
        "chicken": make("鸡胸肉", "肉类"),
        "beef": make("牛肉", "肉类"),
        "greens": make("青菜", "蔬菜"),
    }


def _days(n: int) -> str:
    from app.core.time import biz_today

    return (biz_today() + timedelta(days=n)).isoformat()


def _batch(client, ing_id: str, weight: str, cost: str, expiry_days: int = 30) -> dict:
    r = client.post("/api/v1/batches", json={
        "ingredient_id": ing_id, "weight": weight,
        "purchase_cost": cost, "expiry_date": _days(expiry_days),
    })
    assert r.status_code == 201, r.text
    return r.json()["data"]["batch"]


def _consume(client, ing_id: str, weight: str) -> dict:
    r = client.post("/api/v1/consumptions", json={"ingredient_id": ing_id, "weight": weight})
    assert r.status_code == 201, r.text
    return r.json()["data"]


def _one(sql: str):
    from sqlalchemy import text

    from app.db.session import SessionLocal

    with SessionLocal() as db:
        return db.execute(text(sql)).first()


# ---------------------------------------------------------------- 6.2 库存价值


def test_stock_value_is_remaining_cost_not_purchase_total(seeded, env):
    """库存价值 = 剩余成本；采购总额 53.00 时消耗 300g 后库存价值 42.20。"""
    # 到期日必须不同：同到期日时 FEFO 退化为按 id 排序，扣哪个批次不确定
    _batch(seeded, env["chicken"], "500", "18.00", expiry_days=2)
    _batch(seeded, env["chicken"], "1000", "35.00", expiry_days=20)
    _consume(seeded, env["chicken"], "300")

    d = seeded.get("/api/v1/stats/overview", params={"granularity": "day"}).json()["data"]
    purchase_db = _one("select coalesce(sum(cost_delta),0) from inventory_transactions where type='purchase'")[0]
    remain_db = _one("select coalesce(sum(remaining_cost),0) from batches")[0]

    assert Decimal(d["stock"]["cost"]) == Decimal(remain_db) == Decimal("42.20")
    assert Decimal(d["purchase"]["total_amount"]) == Decimal(purchase_db) == Decimal("53.00")
    assert Decimal(d["stock"]["cost"]) != Decimal(d["purchase"]["total_amount"]), \
        "库存价值不得等同于采购总额"


def test_amounts_match_ledger(seeded, env):
    """采购/消耗金额与流水核算逐项一致。"""
    _batch(seeded, env["chicken"], "500", "18.00")
    _batch(seeded, env["greens"], "400", "8.00")
    _consume(seeded, env["chicken"], "200")
    _consume(seeded, env["greens"], "100")

    d = seeded.get("/api/v1/stats/overview", params={"granularity": "day"}).json()["data"]
    p = Decimal(_one("select coalesce(sum(cost_delta),0) from inventory_transactions where type='purchase'")[0])
    c = Decimal(_one("select coalesce(-sum(cost_delta),0) from inventory_transactions where type='consume'")[0])
    assert Decimal(d["purchase"]["total_amount"]) == p
    assert Decimal(d["consumption"]["total_amount"]) == c


# ---------------------------------------------------------------- 6.3/6.4 粒度


@pytest.mark.parametrize("granularity,min_points", [("day", 7), ("week", 4), ("month", 2), ("year", 1)])
def test_granularity_series(seeded, env, granularity, min_points):
    _batch(seeded, env["chicken"], "500", "18.00")
    _consume(seeded, env["chicken"], "100")

    d = seeded.get("/api/v1/stats/overview", params={"granularity": granularity}).json()["data"]
    series = d["series"]
    assert len(series) >= min_points
    assert all("bucket" in s and "purchase_amount" in s and "consumption_amount" in s for s in series)
    # 序列之和 == 总计（不重复计算）
    assert sum(Decimal(s["purchase_amount"]) for s in series) == Decimal(d["purchase"]["total_amount"])
    assert sum(Decimal(s["consumption_amount"]) for s in series) == Decimal(d["consumption"]["total_amount"])


def test_custom_range_excludes_outside(seeded, env):
    """自定义区间外的流水不计入；含首日、不含次日。"""
    _batch(seeded, env["chicken"], "500", "18.00")  # 今天
    today = _days(0)
    tomorrow = _days(1)

    inside = seeded.get("/api/v1/stats/overview", params={
        "granularity": "day", "from_date": today, "to_date": today,
    }).json()["data"]
    assert Decimal(inside["purchase"]["total_amount"]) == Decimal("18.00")

    outside = seeded.get("/api/v1/stats/overview", params={
        "granularity": "day", "from_date": tomorrow, "to_date": tomorrow,
    }).json()["data"]
    assert Decimal(outside["purchase"]["total_amount"]) == 0
    assert len(outside["series"]) == 1


def test_invalid_range_rejected(seeded, env):
    r = seeded.get("/api/v1/stats/overview", params={
        "granularity": "day", "from_date": _days(0), "to_date": _days(-1),
    })
    assert r.status_code == 400


# ---------------------------------------------------------------- 6.5 分类占比


def test_category_breakdown_uses_consumption(seeded, env):
    """分类占比按消耗成本分组，肉类 2 笔 + 蔬菜 1 笔。"""
    _batch(seeded, env["chicken"], "1000", "40.00")
    _batch(seeded, env["greens"], "500", "10.00")
    _consume(seeded, env["chicken"], "200")   # 8.00
    _consume(seeded, env["greens"], "100")    # 2.00

    d = seeded.get("/api/v1/stats/overview", params={"granularity": "day"}).json()["data"]
    rows = {r["name"]: Decimal(r["amount"]) for r in d["category_breakdown"]}
    assert rows["肉类"] == Decimal("8.00")
    assert rows["蔬菜"] == Decimal("2.00")
    total = sum(rows.values())
    assert total == Decimal(d["consumption"]["total_amount"])
    ratio_sum = sum(Decimal(r["ratio"]) for r in d["category_breakdown"])
    assert abs(ratio_sum - Decimal("1")) < Decimal("0.001")


# ---------------------------------------------------------------- 6.6 排行


def test_top_consumed_ordered_by_weight(seeded, env):
    _batch(seeded, env["chicken"], "1000", "40.00")
    _batch(seeded, env["beef"], "1000", "80.00")
    _consume(seeded, env["chicken"], "300")
    _consume(seeded, env["beef"], "100")
    _consume(seeded, env["beef"], "50")

    d = seeded.get("/api/v1/stats/overview", params={"granularity": "day"}).json()["data"]
    top = d["top_consumed"]
    assert top[0]["name"] == "鸡胸肉"
    assert Decimal(top[0]["weight"]) == Decimal("300.000")
    beef = next(t for t in top if t["name"] == "牛肉")
    assert Decimal(beef["weight"]) == Decimal("150.000")
    assert beef["times"] == 2


# ---------------------------------------------------------------- 6.8 周转


def test_turnover_counts_purchase_and_consume(seeded, env):
    _batch(seeded, env["chicken"], "500", "18.00")
    _batch(seeded, env["chicken"], "500", "18.00")
    _consume(seeded, env["chicken"], "200")
    _consume(seeded, env["chicken"], "100")

    d = seeded.get("/api/v1/stats/overview", params={"granularity": "day"}).json()["data"]
    row = next(r for r in d["turnover"] if r["name"] == "鸡胸肉")
    assert row["purchase_times"] == 2
    assert row["consume_times"] == 2
    assert Decimal(row["consumed_weight"]) == Decimal("300.000")


# ---------------------------------------------------------------- 撤销


def test_reverse_updates_stats(seeded, env):
    """撤销消耗后，消耗总额与分类占比同步减少（reverse 净额抵消）。"""
    _batch(seeded, env["chicken"], "1000", "40.00")
    c = _consume(seeded, env["chicken"], "200")  # 8.00
    before = seeded.get("/api/v1/stats/overview", params={"granularity": "day"}).json()["data"]
    assert Decimal(before["consumption"]["total_amount"]) == Decimal("8.00")

    seeded.post(f"/api/v1/consumptions/{c['consumption']['id']}/reverse", json={"reason": "统计口径"})
    after = seeded.get("/api/v1/stats/overview", params={"granularity": "day"}).json()["data"]
    assert Decimal(after["consumption"]["total_amount"]) == 0
    assert sum(Decimal(r["amount"]) for r in after["category_breakdown"]) == 0


# ---------------------------------------------------------------- 空态与鉴权


def test_empty_state(seeded, env):
    d = seeded.get("/api/v1/stats/overview", params={"granularity": "day"}).json()["data"]
    assert d["has_data"] is False
    assert Decimal(d["purchase"]["total_amount"]) == 0
    assert len(d["series"]) > 0            # 时间轴仍然给出
    assert d["top_consumed"] == []
    assert d["category_breakdown"] == []


def test_stats_requires_login(client):
    assert client.get("/api/v1/stats/overview").status_code == 401


# ---------------------------------------------------------------- 最近操作


def test_recent_operations(seeded, env):
    _batch(seeded, env["chicken"], "500", "18.00")
    _consume(seeded, env["chicken"], "100")
    d = seeded.get("/api/v1/stats/overview", params={"granularity": "day"}).json()["data"]
    ops = d["recent_operations"]
    assert len(ops) == 2
    assert {o["type"] for o in ops} == {"purchase", "consume"}
