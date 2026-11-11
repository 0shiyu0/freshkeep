"""阶段 5 后端支撑：库存列表的状态筛选与多条件组合。

前端「库存总览」要支持 5.3 的四种状态（正常/临期/过期/无库存）与
搜索、分类、位置**组合**筛选，这些必须由 `/inventory` 一个接口完成，
避免前端多次拉全量再本地过滤（会导致分页与后端不一致）。
"""
from __future__ import annotations

from decimal import Decimal

import pytest


@pytest.fixture()
def env(seeded):
    """两个食材 + 一个分类 + 一个位置，日期全部相对今天。"""
    from app.db.session import SessionLocal
    from app.models import Category, StorageLocation, Unit

    with SessionLocal() as db:
        g = db.query(Unit).filter_by(symbol="g").first()
        loc = db.query(StorageLocation).filter_by(name="冷冻室").first()
        # seeded 已建了 root 分类「肉类」，存在就复用（ux_categories_root_name 唯一）
        cat = db.query(Category).filter_by(name="肉类", parent_id=None).first()
        if cat is None:
            cat = Category(name="肉类")
            db.add(cat)
            db.commit()
            db.refresh(cat)
        gid, lid, cid = str(g.id), str(loc.id), str(cat.id)

    ids = {}
    for name in ("鸡胸肉", "牛奶"):
        r = seeded.post("/api/v1/ingredients", json={
            "name": name, "default_weight_unit_id": gid, "category_id": cid,
        })
        assert r.status_code == 201, r.text
        ids[name] = r.json()["data"]["id"]
    return {"ing": ids, "location_id": lid, "category_id": cid, "g_id": gid}


def _days(n: int) -> str:
    from datetime import timedelta

    from app.core.time import biz_today

    return (biz_today() + timedelta(days=n)).isoformat()


def _batch(client, ing_id: str, weight: str, cost: str, **extra) -> dict:
    payload = {"ingredient_id": ing_id, "weight": weight, "purchase_cost": cost, **extra}
    r = client.post("/api/v1/batches", json=payload)
    assert r.status_code == 201, r.text
    return r.json()["data"]["batch"]


def _list(client, **params) -> dict:
    r = client.get("/api/v1/inventory", params=params)
    assert r.status_code == 200, r.text
    return r.json()["data"]


# ---------------------------------------------------------------- 四种状态


def test_status_expiring_only_7d_with_stock(seeded, env):
    _batch(seeded, env["ing"]["鸡胸肉"], "500", "18.00", expiry_date=_days(2))
    _batch(seeded, env["ing"]["牛奶"], "1000", "12.00", expiry_date=_days(30))
    data = _list(seeded, status="expiring")
    names = [i["name"] for i in data["items"]]
    assert "鸡胸肉" in names and "牛奶" not in names


def test_status_expired_only_past_with_stock(seeded, env):
    _batch(seeded, env["ing"]["鸡胸肉"], "500", "18.00", expiry_date=_days(-1))
    _batch(seeded, env["ing"]["牛奶"], "1000", "12.00", expiry_date=_days(20))
    data = _list(seeded, status="expired")
    names = [i["name"] for i in data["items"]]
    assert "鸡胸肉" in names and "牛奶" not in names


def test_status_out_of_stock(seeded, env):
    """无批次或批次已清空的食材归入「无库存」。"""
    # 牛奶没有任何批次
    data = _list(seeded, status="out_of_stock")
    names = [i["name"] for i in data["items"]]
    assert "牛奶" in names

    # 鸡胸肉入库后清空 → 也应进入无库存
    b = _batch(seeded, env["ing"]["鸡胸肉"], "100", "3.00")
    seeded.post("/api/v1/inventory/adjustments", json={
        "batch_id": b["id"], "actual_weight": "0", "reason": "阶段5 清空",
    })
    names2 = [i["name"] for i in _list(seeded, status="out_of_stock")["items"]]
    assert "鸡胸肉" in names2


def test_status_normal_excludes_expiring_and_empty(seeded, env):
    _batch(seeded, env["ing"]["鸡胸肉"], "500", "18.00", expiry_date=_days(20))
    _batch(seeded, env["ing"]["牛奶"], "1000", "12.00", expiry_date=_days(2))
    names = [i["name"] for i in _list(seeded, status="normal")["items"]]
    assert "鸡胸肉" in names and "牛奶" not in names


def test_unknown_status_rejected(seeded, env):
    """非法状态被拒；本项目把参数校验统一映射成 400 VALIDATION_ERROR（不是 422）。"""
    r = seeded.get("/api/v1/inventory", params={"status": "whatever"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------- 组合筛选


def test_combined_filters(seeded, env):
    """搜索 + 分类 + 状态 + 位置 同时生效（返回交集）。"""
    _batch(seeded, env["ing"]["鸡胸肉"], "500", "18.00",
           expiry_date=_days(2), storage_location_id=env["location_id"])
    _batch(seeded, env["ing"]["牛奶"], "1000", "12.00", expiry_date=_days(30))

    # 全部条件命中鸡胸肉
    d1 = _list(seeded, q="鸡", category_id=env["category_id"], status="expiring",
               location_id=env["location_id"])
    assert [i["name"] for i in d1["items"]] == ["鸡胸肉"]

    # 位置换成不存在的位置 → 空
    d2 = _list(seeded, q="鸡", status="expiring", location_id="00000000-0000-0000-0000-000000000000")
    assert d2["total"] == 0

    # 拼音搜索 + 状态组合
    d3 = _list(seeded, q="jixiong", status="expiring")
    assert [i["name"] for i in d3["items"]] == ["鸡胸肉"]

    # 状态与搜索冲突 → 空（牛奶不临期）
    d4 = _list(seeded, q="牛", status="expiring")
    assert d4["total"] == 0


def test_list_returns_aggregates(seeded, env):
    """列表项必须带库存聚合，前端总览才能与后端一致。"""
    _batch(seeded, env["ing"]["鸡胸肉"], "500", "18.00", expiry_date=_days(3))
    _batch(seeded, env["ing"]["鸡胸肉"], "1000", "35.00", expiry_date=_days(20))
    seeded.post("/api/v1/consumptions", json={"ingredient_id": env["ing"]["鸡胸肉"], "weight": "300"})

    row = next(i for i in _list(seeded)["items"] if i["name"] == "鸡胸肉")
    assert row["total_weight"] == "1200.000"
    assert row["total_cost"] == "42.20"
    assert row["batch_count"] == 2
    assert row["nearest_expiry"] == _days(3)
    assert row["days_to_expiry"] == 3
    assert Decimal(row["minimum_weight"]) == 0
