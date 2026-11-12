"""M3 批次域接口测试：入库五步事务、批次查询、元数据修改、临期查询。

核心断言（对应 AGENTS.md §4.2 库存写入五步与 PRD §5.1）：
- 入库必须同时产生 batches / inventory_transactions / transaction_allocations 三表记录；
- Σ allocation == transaction.delta == batch.remaining_*（初始入库时三者相等）；
- v_batch_reconcile 的三个 diff 必须为 0；
- 批次数量不可直接改（要走盘点），元数据可改。

注意：**不在模块层 import app 下的任何模块**（否则 engine 会在 conftest 切到测试库之前
就绑定默认库——这正是 test_system.py 注释里踩过的坑）。
"""
from __future__ import annotations

from decimal import Decimal

import pytest


@pytest.fixture()
def units_map(seeded):
    """单位字典：按符号取 id。"""
    from app.db.session import SessionLocal
    from app.models import Unit

    with SessionLocal() as db:
        rows = db.query(Unit).all()
        # 值转成 str：httpx 的 json= 参数用标准 json.dumps，UUID 对象会抛 TypeError
        return {u.symbol: str(u.id) for u in rows}


@pytest.fixture()
def ingredient(seeded):
    """一个可入库的食材：默认数量单位=包、重量单位=克、每包 250g。"""
    from decimal import Decimal as D

    from app.db.session import SessionLocal
    from app.models import Ingredient, Unit

    with SessionLocal() as db:
        units = db.query(Unit).all()
        by_name = {u.name: u for u in units}
        ing = Ingredient(
            name="鸡胸肉",
            default_quantity_unit_id=by_name["包"].id,
            default_weight_unit_id=by_name["克"].id,
            default_unit_weight=D("250"),
        )
        db.add(ing)
        db.commit()
        db.refresh(ing)
        return {"id": str(ing.id), "name": ing.name}


def _db_one(sql: str):
    from app.db.session import SessionLocal
    from sqlalchemy import text

    with SessionLocal() as db:
        return db.execute(text(sql)).first()


# ---------------------------------------------------------------- 创建


def test_create_batch_weight_purchase(seeded, ingredient, units_map):
    """按重量入库：500g / 18 元 → 五步事务三表齐全，对账 diff 为 0。"""
    res = seeded.post(
        "/api/v1/batches",
        json={
            "ingredient_id": ingredient["id"],
            "weight": "500",
            "weight_unit_id": units_map["g"],
            "purchase_cost": "18.00",
        },
    )
    assert res.status_code == 201, res.text
    data = res.json()["data"]

    batch = data["batch"]
    assert batch["batch_no"].endswith("-01")
    assert batch["status"] == "active"
    assert batch["initial_weight"] == "500.000"
    assert batch["remaining_weight"] == "500.000"
    assert batch["purchase_cost"] == "18.00"
    assert batch["remaining_cost"] == "18.00"

    tx = data["transaction"]
    assert tx["type"] == "purchase"
    assert tx["weight_delta"] == "500.000"
    assert tx["cost_delta"] == "18.00"

    # 五步断言：流水、分配、批次缓存三者一致
    row = _db_one(
        "SELECT t.weight_delta, a.weight_delta AS alloc_w, a.cost_delta AS alloc_c, "
        "a.unit_cost, t.related_object_type "
        "FROM inventory_transactions t "
        "JOIN transaction_allocations a ON a.transaction_id = t.id"
    )
    assert row is not None, "入库必须同时写流水与分配"
    assert Decimal(row[0]) == Decimal(row[1]) == Decimal("500.000")
    assert Decimal(row[2]) == Decimal("18.00")
    assert Decimal(row[3]) == Decimal("0.0360")  # 18 / 500，4 位精度
    assert row[4] == "batch"

    # 对账视图：三个 diff 全 0
    diff = _db_one("SELECT diff_quantity, diff_weight, diff_cost FROM v_batch_reconcile")
    assert tuple(Decimal(x) for x in diff) == (Decimal(0), Decimal(0), Decimal(0))


def test_create_batch_quantity_only(seeded, ingredient):
    """纯数量入库（按数量管理的食材）：2 包 / 10 元。"""
    res = seeded.post(
        "/api/v1/batches",
        json={"ingredient_id": ingredient["id"], "quantity": "2", "purchase_cost": "10.00"},
    )
    assert res.status_code == 201, res.text
    batch = res.json()["data"]["batch"]
    assert batch["initial_quantity"] == "2.000"
    assert batch["remaining_quantity"] == "2.000"
    # 单位成本按数量算：10 / 2 = 5.0000
    row = _db_one("SELECT unit_cost FROM transaction_allocations")
    assert Decimal(row[0]) == Decimal("5.0000")
    diff = _db_one("SELECT diff_quantity, diff_weight, diff_cost FROM v_batch_reconcile")
    assert tuple(Decimal(x) for x in diff) == (Decimal(0), Decimal(0), Decimal(0))


def test_create_batch_dual_measurement(seeded, ingredient):
    """双计量：2 包 + 500g 同时入库，两者都记录。"""
    res = seeded.post(
        "/api/v1/batches",
        json={
            "ingredient_id": ingredient["id"],
            "quantity": "2",
            "weight": "500",
            "purchase_cost": "18.00",
        },
    )
    assert res.status_code == 201, res.text
    batch = res.json()["data"]["batch"]
    assert batch["initial_quantity"] == "2.000"
    assert batch["initial_weight"] == "500.000"


def test_create_batch_numbering_increments(seeded, ingredient):
    """同日两次入库：批次号 -01、-02，流水号也递增。"""
    from app.db.session import SessionLocal
    from sqlalchemy import text

    for _ in range(2):
        res = seeded.post(
            "/api/v1/batches",
            json={"ingredient_id": ingredient["id"], "weight": "100"},
        )
        assert res.status_code == 201, res.text
    with SessionLocal() as db:
        nos = [r[0] for r in db.execute(text("SELECT batch_no FROM batches ORDER BY created_at")).all()]
        txn = [r[0] for r in db.execute(text("SELECT transaction_no FROM inventory_transactions ORDER BY created_at")).all()]
    assert nos[0].endswith("-01") and nos[1].endswith("-02")
    assert len({*txn}) == 2  # 流水号唯一


def test_create_batch_kg_converted_to_grams(seeded, ingredient, units_map):
    """weight 用 kg 传入 → 换算成克存储。"""
    res = seeded.post(
        "/api/v1/batches",
        json={
            "ingredient_id": ingredient["id"],
            "weight": "1.5",
            "weight_unit_id": units_map["kg"],
            "purchase_cost": "30.00",
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["data"]["batch"]["initial_weight"] == "1500.000"


# ---------------------------------------------------------------- 创建的校验与拒绝


def test_create_batch_rejects_all_zero(seeded, ingredient):
    """数量与重量都为 0 → 400（批次必须有实体）。"""
    res = seeded.post(
        "/api/v1/batches", json={"ingredient_id": ingredient["id"], "weight": "0", "quantity": "0"}
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_create_batch_rejects_negative(seeded, ingredient):
    res = seeded.post(
        "/api/v1/batches", json={"ingredient_id": ingredient["id"], "weight": "-5"}
    )
    assert res.status_code in (400, 422)


def test_create_batch_rejects_wrong_unit_dimension(seeded, ingredient, units_map):
    """重量位填数量类单位（包）→ 400。"""
    res = seeded.post(
        "/api/v1/batches",
        json={
            "ingredient_id": ingredient["id"],
            "weight": "500",
            "weight_unit_id": units_map["包"],
        },
    )
    assert res.status_code == 400


def test_create_batch_unknown_ingredient(seeded):
    res = seeded.post(
        "/api/v1/batches",
        json={"ingredient_id": "00000000-0000-0000-0000-000000000000", "weight": "100"},
    )
    assert res.status_code == 404


def test_create_batch_rejects_expiry_before_production(seeded, ingredient):
    """到期日早于生产日 → 400（DDL 也有约束，但接口层先给友好错误）。"""
    from datetime import timedelta

    from app.core.time import biz_today

    today = biz_today()
    res = seeded.post(
        "/api/v1/batches",
        json={
            "ingredient_id": ingredient["id"],
            "weight": "100",
            "production_date": today.isoformat(),
            "expiry_date": (today - timedelta(days=1)).isoformat(),
        },
    )
    assert res.status_code == 400


def test_create_batch_requires_login(client):
    res = client.post("/api/v1/batches", json={"weight": "100"})
    assert res.status_code == 401


# ---------------------------------------------------------------- 查询


def test_batch_list_and_filters(seeded, ingredient):
    # 日期一律相对今天计算：硬编码绝对日期会随时间推移让测试失效
    from datetime import timedelta

    from app.core.time import biz_today

    today = biz_today()
    ing2 = seeded.post("/api/v1/ingredients", json={"name": "牛奶"})
    ing2_id = ing2.json()["data"]["id"]

    seeded.post(
        "/api/v1/batches",
        json={"ingredient_id": ingredient["id"], "weight": "500",
              "expiry_date": (today + timedelta(days=2)).isoformat()},
    )
    seeded.post(
        "/api/v1/batches",
        json={"ingredient_id": ing2_id, "weight": "1000",
              "expiry_date": (today + timedelta(days=12)).isoformat()},
    )

    # 与阶段 2 的 GET /ingredients 保持同一分页结构：data.items 是数组
    all_data = seeded.get("/api/v1/batches").json()["data"]
    assert all_data["total"] == 2
    assert len(all_data["items"]) == 2

    by_ing = seeded.get(
        "/api/v1/batches", params={"ingredient_id": ingredient["id"]}
    ).json()["data"]
    assert by_ing["total"] == 1
    assert by_ing["items"][0]["ingredient_name"] == "鸡胸肉"


def test_batch_detail(seeded, ingredient):
    created = seeded.post(
        "/api/v1/batches",
        json={"ingredient_id": ingredient["id"], "weight": "500", "note": "第一批"},
    ).json()["data"]["batch"]
    res = seeded.get(f"/api/v1/batches/{created['id']}")
    assert res.status_code == 200
    d = res.json()["data"]
    assert d["id"] == created["id"]
    assert d["note"] == "第一批"
    assert d["ingredient_name"] == "鸡胸肉"


def test_batch_detail_404(seeded):
    res = seeded.get("/api/v1/batches/00000000-0000-0000-0000-000000000000")
    assert res.status_code == 404


def test_expiring_and_expired_batches(seeded, ingredient):
    """临期按天过滤；过期单列；无到期日不进临期。

    日期相对今天计算：绝对日期会让测试在次日失效（曾因硬编码 11-11 在 11-10 变红）。
    """
    from datetime import timedelta

    from app.core.time import biz_today

    today = biz_today()
    seeded.post(  # 2 天后到期 → 临期
        "/api/v1/batches",
        json={"ingredient_id": ingredient["id"], "weight": "100",
              "expiry_date": (today + timedelta(days=2)).isoformat()},
    )
    seeded.post(  # 10 天后到期 → 不在 7 天窗口
        "/api/v1/batches",
        json={"ingredient_id": ingredient["id"], "weight": "100",
              "expiry_date": (today + timedelta(days=10)).isoformat()},
    )
    seeded.post(  # 已过期
        "/api/v1/batches",
        json={"ingredient_id": ingredient["id"], "weight": "100",
              "expiry_date": (today - timedelta(days=1)).isoformat()},
    )
    seeded.post(  # 无到期日
        "/api/v1/batches",
        json={"ingredient_id": ingredient["id"], "weight": "100"},
    )

    expiring = seeded.get("/api/v1/batches/expiring", params={"days": 7}).json()["data"]["items"]
    assert len(expiring) == 1
    assert expiring[0]["days_to_expiry"] == 2

    expired = seeded.get("/api/v1/batches/expired").json()["data"]["items"]
    assert len(expired) == 1
    assert expired[0]["days_to_expiry"] is not None and expired[0]["days_to_expiry"] < 0


# ---------------------------------------------------------------- 元数据修改


def test_update_batch_meta(seeded, ingredient):
    from datetime import timedelta

    from app.core.time import biz_today

    target = (biz_today() + timedelta(days=20)).isoformat()
    created = seeded.post(
        "/api/v1/batches", json={"ingredient_id": ingredient["id"], "weight": "500"}
    ).json()["data"]["batch"]
    res = seeded.put(
        f"/api/v1/batches/{created['id']}",
        json={"expiry_date": target, "note": "放在冷冻室最里层"},
    )
    assert res.status_code == 200, res.text
    d = res.json()["data"]
    assert d["expiry_date"] == target
    assert d["note"] == "放在冷冻室最里层"


def test_update_batch_rejects_quantity_fields(seeded, ingredient):
    """数量/成本/状态不可直接改（数量要走盘点、状态走状态机）→ 400。"""
    created = seeded.post(
        "/api/v1/batches", json={"ingredient_id": ingredient["id"], "weight": "500"}
    ).json()["data"]["batch"]
    for forbidden in (
        {"remaining_weight": "400"},
        {"initial_quantity": "9"},
        {"purchase_cost": "1.00"},
        {"status": "depleted"},
    ):
        res = seeded.put(f"/api/v1/batches/{created['id']}", json=forbidden)
        assert res.status_code == 400, f"{forbidden} 不应被接受"


def test_update_unknown_batch(seeded):
    res = seeded.put(
        "/api/v1/batches/00000000-0000-0000-0000-000000000000", json={"note": "x"}
    )
    assert res.status_code == 404
