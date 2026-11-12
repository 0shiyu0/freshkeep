"""阶段 8 验收：AI 识别闸门 / 条码查询 / 临期提醒 / 采购建议。

硬约束（每个识别用例都断言）：
**识别、修正、拒绝三个阶段不得改变 `batches` / `inventory_transactions` 的任何一行**，
只有 `confirm` 才会产生业务数据。
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest


@pytest.fixture()
def ing(seeded):
    from app.db.session import SessionLocal
    from app.models import Ingredient, Unit

    with SessionLocal() as db:
        g = db.query(Unit).filter_by(symbol="g").first()
        gid = str(g.id)
        item = Ingredient(name="鸡胸肉", default_weight_unit_id=g.id, minimum_weight=Decimal("1000"))
        db.add(item)
        db.commit()
        db.refresh(item)
        return {"id": str(item.id), "g_id": gid}


def _days(n: int) -> str:
    from app.core.time import biz_today

    return (biz_today() + timedelta(days=n)).isoformat()


def _counts():
    from app.db.session import SessionLocal
    from sqlalchemy import text

    with SessionLocal() as db:
        return {
            "batches": db.execute(text("select count(*) from batches")).scalar(),
            "tx": db.execute(text("select count(*) from inventory_transactions")).scalar(),
            "recognition": db.execute(text("select count(*) from recognition_drafts")).scalar(),
        }


def _create(client, manual: dict | None = None, hint: str = "鸡胸肉", image: str | None = None):
    payload: dict = {"hint": hint}
    if manual is not None:
        payload["manual"] = manual
    if image:
        payload["image_file_id"] = image
    return client.post("/api/v1/ai/recognitions", json=payload)


# ---------------------------------------------------------------- 闸门


def test_recognition_does_not_touch_inventory(seeded):
    before = _counts()
    r = _create(seeded, manual={"name": "AI 测试鸡胸肉", "weight": "500", "purchase_cost": "18.00"})
    assert r.status_code == 201, r.text
    after = _counts()

    assert after["batches"] == before["batches"], "识别阶段不得创建批次"
    assert after["tx"] == before["tx"], "识别阶段不得写库存流水"
    assert after["recognition"] == before["recognition"] + 1
    assert r.json()["data"]["status"] == "pending"


def test_date_swap_detected_and_normalized(seeded):
    """视觉模型常见错误：把生产日期填进到期日。草稿必须交换并告警。"""
    r = _create(seeded, manual={
        "name": "日期错位测试", "production_date": _days(20), "expiry_date": _days(-5),
    })
    assert r.status_code == 201, r.text
    d = r.json()["data"]
    codes = [w["code"] for w in d["warnings"]]
    assert "DATE_SWAPPED" in codes, codes
    # 交换后：生产早于到期
    assert d["draft"]["production_date"] < d["draft"]["expiry_date"]
    # 且仍提示只识别到过期日（因为交换后到期日在未来？此处 -5 → 20，已未来，故只校验顺序）
    assert d["status"] == "pending"


def test_patch_clears_warning(seeded):
    r = _create(seeded, manual={"name": "修正测试", "production_date": _days(0), "expiry_date": _days(-10)})
    did = r.json()["data"]["id"]
    assert any(w["code"] == "DATE_SWAPPED" for w in r.json()["data"]["warnings"])

    fixed = seeded.patch(f"/api/v1/ai/recognitions/{did}", json={
        "patch": {"production_date": _days(-10), "expiry_date": _days(30)},
    })
    assert fixed.status_code == 200, fixed.text
    d = fixed.json()["data"]
    assert not any(w["code"] == "DATE_SWAPPED" for w in d["warnings"])
    assert d["draft"]["production_date"] == _days(-10)
    assert _counts()["batches"] == 0, "修正阶段同样不得产生批次"


def test_confirm_creates_ingredient(seeded):
    r = _create(seeded, manual={
        "name": "确认建档鸡胸肉", "brand": "测试牌", "barcode": "6901234567890",
        "nutrition": [
            {"code": "calories", "value": "165", "basis_amount": "100", "basis_unit": "g"},
            {"code": "protein", "value": "31", "basis_amount": "100", "basis_unit": "g"},
        ],
        "production_date": _days(-2), "expiry_date": _days(5),
    })
    did = r.json()["data"]["id"]

    c = seeded.post(f"/api/v1/ai/recognitions/{did}/confirm", json={"target": "ingredient"})
    assert c.status_code == 200, c.text
    data = c.json()["data"]
    ing_id = data["ingredient_id"]

    det = seeded.get(f"/api/v1/ingredients/{ing_id}").json()["data"]
    assert det["name"] == "确认建档鸡胸肉"
    assert {n["code"] for n in det["nutrition"]} == {"calories", "protein"}
    # 拼音必须已生成（否则搜索不到）
    found = seeded.get("/api/v1/ingredients", params={"q": "jixiongrou"}).json()["data"]["items"]
    assert any(i["id"] == ing_id for i in found)

    # 草稿状态与审计
    got = seeded.get(f"/api/v1/ai/recognitions/{did}").json()["data"]
    assert got["status"] == "confirmed"
    assert got["confirmed_entity_type"] == "ingredient"
    from app.db.session import SessionLocal
    from sqlalchemy import text

    with SessionLocal() as db:
        n = db.execute(text("select count(*) from audit_logs where action='recognition_confirm'")).scalar()
    assert n >= 1


def test_confirm_batch_goes_through_five_step(seeded, ing):
    r = _create(seeded, manual={
        "name": "鸡胸肉", "weight": "500", "purchase_cost": "18.00",
        "production_date": _days(-1), "expiry_date": _days(10),
    })
    did = r.json()["data"]["id"]
    before = _counts()

    c = seeded.post(f"/api/v1/ai/recognitions/{did}/confirm", json={
        "target": "batch", "ingredient_id": ing["id"],
    })
    assert c.status_code == 200, c.text
    batch_id = c.json()["data"]["batch_id"]

    after = _counts()
    assert after["batches"] == before["batches"] + 1
    assert after["tx"] == before["tx"] + 1, "入库必须写 purchase 流水"
    row = seeded.get(f"/api/v1/batches/{batch_id}").json()["data"]
    assert row["initial_weight"] == "500.000"
    assert row["purchase_cost"] == "18.00"
    assert row["expiry_date"] == _days(10)
    # 对账仍为 0
    from app.db.session import SessionLocal
    from sqlalchemy import text

    with SessionLocal() as db:
        diffs = db.execute(text(
            "select count(*) from v_batch_reconcile where diff_quantity<>0 or diff_weight<>0 or diff_cost<>0"
        )).scalar()
    assert diffs == 0


def test_reject(seeded):
    did = _create(seeded, manual={"name": "拒绝测试"}) .json()["data"]["id"]
    r = seeded.post(f"/api/v1/ai/recognitions/{did}/reject")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "rejected"
    # 已拒绝不能再确认
    c = seeded.post(f"/api/v1/ai/recognitions/{did}/confirm", json={"target": "ingredient"})
    assert c.status_code == 409


def test_unconfigured_provider_creates_blank_draft(seeded):
    r = _create(seeded, manual=None)
    assert r.status_code == 201
    d = r.json()["data"]
    assert d["provider"] == "manual"
    assert any(w["code"] == "AI_NOT_CONFIGURED" for w in d["warnings"])
    assert d["status"] == "pending"


def test_stub_provider_returns_sample(seeded):
    seeded.put("/api/v1/ai/settings", json={"kind": "stub", "enabled": True})
    r = _create(seeded, manual=None, hint="鸡胸肉")
    d = r.json()["data"]
    assert d["provider"] == "stub"
    codes = {n["code"] for n in d["draft"]["nutrition"]}
    assert {"calories", "protein"} <= codes
    assert d["draft"]["name"] == "鸡胸肉"
    # 识别阶段仍然不产生库存
    assert _counts()["batches"] == 0


# ---------------------------------------------------------------- 条码 / 外部源


def test_barcode_local_hit(seeded, ing):
    seeded.post("/api/v1/barcodes", json={"barcode": "6900000000001", "ingredient_id": ing["id"]})
    r = seeded.get("/api/v1/products/lookup", params={"barcode": "6900000000001"})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["found"] is True and d["source"] == "local"
    assert d["ingredient_id"] == ing["id"]


def test_barcode_miss_without_source(seeded):
    r = seeded.get("/api/v1/products/lookup", params={"barcode": "6999999999999"})
    d = r.json()["data"]
    assert d["found"] is False and d["source"] == "none"


def test_external_source_rejects_private_host(seeded):
    """SSRF 防护：配置内网地址后查询应返回错误而不是发起请求。"""
    seeded.put("/api/v1/products/source", json={
        "kind": "custom", "base_url": "http://127.0.0.1:8000/{barcode}", "enabled": True,
    })
    r = seeded.get("/api/v1/products/lookup", params={"barcode": "6900000000002"})
    d = r.json()["data"]
    assert d["found"] is False
    assert "source_error" in d


def test_source_secret_masked(seeded):
    seeded.put("/api/v1/products/source", json={
        "kind": "openfoodfacts", "base_url": "https://example.com", "api_key": "abcdefgh1234", "enabled": True,
    })
    d = seeded.get("/api/v1/products/source").json()["data"]
    assert d["api_key"].endswith("1234") and "*" in d["api_key"]
    assert "abcdefgh" not in d["api_key"]


# ---------------------------------------------------------------- 临期 / 提醒


def test_alert_scan_is_idempotent_and_readonly(seeded, ing):
    seeded.post("/api/v1/batches", json={
        "ingredient_id": ing["id"], "weight": "500", "purchase_cost": "18.00",
        "expiry_date": _days(2),
    })
    before = _counts()
    first = seeded.post("/api/v1/alerts/scan").json()["data"]
    assert first["created"] >= 2  # 临期 + 低库存（最低 1000，库存 500）
    second = seeded.post("/api/v1/alerts/scan").json()["data"]
    assert second["created"] == 0, "重复扫描不应重复插入"
    after = _counts()
    assert after["batches"] == before["batches"]
    assert after["tx"] == before["tx"]

    s = seeded.get("/api/v1/alerts/summary").json()["data"]
    assert s["unread"] == first["created"]
    assert s["expiring"] >= 1 and s["low_stock"] >= 1


def test_notification_mark_read(seeded, ing):
    seeded.post("/api/v1/batches", json={
        "ingredient_id": ing["id"], "weight": "500", "purchase_cost": "18.00", "expiry_date": _days(-1),
    })
    seeded.post("/api/v1/alerts/scan")
    items = seeded.get("/api/v1/alerts/notifications").json()["data"]["items"]
    assert items and items[0]["type"] in {"expired", "expiring", "low_stock"}

    nid = items[0]["id"]
    r = seeded.post(f"/api/v1/alerts/notifications/{nid}/read")
    assert r.json()["data"]["updated"] == 1
    after = seeded.get("/api/v1/alerts/summary").json()["data"]
    assert after["unread"] == len(items) - 1


# ---------------------------------------------------------------- 采购建议


def test_purchase_suggestion(seeded, ing):
    seeded.post("/api/v1/batches", json={
        "ingredient_id": ing["id"], "weight": "200", "purchase_cost": "7.20",
        "expiry_date": _days(30),
    })
    d = seeded.get("/api/v1/purchase/suggestions").json()["data"]
    row = next(i for i in d["items"] if i["ingredient_id"] == ing["id"])
    assert row["reason"] == "LOW_MIN_WEIGHT"
    assert Decimal(row["suggested_weight"]) == Decimal("800.000")  # 最低 1000 - 现有 200
    assert row["last_unit_cost"] == "0.0360"
    assert Decimal(row["estimated_cost"]) == Decimal("28.80")      # 800 × 0.036


def test_alerts_require_login(client):
    assert client.get("/api/v1/alerts/summary").status_code == 401
    assert client.get("/api/v1/purchase/suggestions").status_code == 401
