"""阶段 2 接口测试：认证 / 字典 / 食材 / 换算 / 图片 / 搜索 / 条码。

跑在真实 PostgreSQL（见 conftest），无库时整套跳过。
"""
from __future__ import annotations

import base64

import pytest

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


# ---------------------------------------------------------------- 认证


def test_requires_login(client, clean_db):
    assert client.get("/api/v1/ingredients").status_code == 401


def test_pair_sets_cookie_and_me_works(client, clean_db):
    from app.db.session import SessionLocal
    from app.services.auth import get_owner, issue_pair_code

    with SessionLocal() as db:
        get_owner(db)
        code = issue_pair_code(db)
        db.commit()

    res = client.post("/api/v1/auth/pair", json={"code": code, "device_name": "t", "platform": "web"})
    assert res.status_code == 200
    assert client.cookies.get("fk_sid")
    me = client.get("/api/v1/auth/me").json()["data"]
    assert me["username"] == "owner"
    assert me["has_password"] is False


def test_pair_code_is_single_use(client, clean_db):
    from app.db.session import SessionLocal
    from app.services.auth import get_owner, issue_pair_code

    with SessionLocal() as db:
        get_owner(db)
        code = issue_pair_code(db)
        db.commit()

    assert client.post("/api/v1/auth/pair", json={"code": code, "platform": "web"}).status_code == 200
    again = client.post("/api/v1/auth/pair", json={"code": code, "platform": "web"})
    assert again.status_code == 401


def test_password_flow(auth_client):
    # 未设置密码时登录应明确报错，而不是"用户名或密码错误"
    res = auth_client.post(
        "/api/v1/auth/login", json={"username": "owner", "password": "whatever1", "platform": "android"}
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "PASSWORD_NOT_SET"

    assert auth_client.post(
        "/api/v1/auth/password/set",
        json={"new_password": "Freshkeep#2026", "confirm_password": "Freshkeep#2026"},
    ).status_code == 200

    ok = auth_client.post(
        "/api/v1/auth/login",
        json={"username": "owner", "password": "Freshkeep#2026", "platform": "android", "device_name": "app"},
    )
    assert ok.status_code == 200
    assert ok.json()["data"]["token"]

    bad = auth_client.post(
        "/api/v1/auth/login", json={"username": "owner", "password": "wrongpass", "platform": "android"}
    )
    assert bad.status_code == 401

    changed = auth_client.post(
        "/api/v1/auth/password",
        json={"old_password": "Freshkeep#2026", "new_password": "Freshkeep#2027", "confirm_password": "Freshkeep#2027"},
    )
    assert changed.status_code == 200


def test_bearer_token_works(auth_client):
    auth_client.post(
        "/api/v1/auth/password/set",
        json={"new_password": "Freshkeep#2026", "confirm_password": "Freshkeep#2026"},
    )
    res = auth_client.post(
        "/api/v1/auth/login",
        json={"username": "owner", "password": "Freshkeep#2026", "platform": "ios", "device_name": "app"},
    )
    token = res.json()["data"]["token"]
    from fastapi.testclient import TestClient

    from app.main import app

    bare = TestClient(app)
    assert bare.get("/api/v1/ingredients").status_code == 401
    assert bare.get("/api/v1/ingredients", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_logout_revokes(auth_client):
    assert auth_client.post("/api/v1/auth/logout").status_code == 200
    # 退出后同一个客户端（Cookie 已被清）再访问应 401
    assert auth_client.get("/api/v1/auth/me").status_code == 401


# ---------------------------------------------------------------- 字典


def test_categories_two_levels_and_duplicate(seeded):
    cats = seeded.get("/api/v1/categories").json()["data"]["items"]
    meat = next(c for c in cats if c["name"] == "肉类")
    common = next(c for c in cats if c["name"] == "常见食材")
    assert common["parent_id"] == meat["id"]
    assert common["parent_name"] == "肉类"

    dup = seeded.post("/api/v1/categories", json={"name": "常见食材", "parent_id": meat["id"]})
    assert dup.status_code == 409


def test_category_cannot_nest_three_levels(seeded):
    cats = seeded.get("/api/v1/categories").json()["data"]["items"]
    common = next(c for c in cats if c["name"] == "常见食材")
    res = seeded.post("/api/v1/categories", json={"name": "三级", "parent_id": common["id"]})
    assert res.status_code == 400


def test_category_delete_blocked_when_used(seeded):
    cats = {c["name"]: c for c in seeded.get("/api/v1/categories").json()["data"]["items"]}
    units = {u["symbol"]: u for u in seeded.get("/api/v1/units").json()["data"]["items"]}
    created = seeded.post(
        "/api/v1/ingredients",
        json={"name": "测试食材", "category_id": cats["常见食材"]["id"], "default_weight_unit_id": units["g"]["id"]},
    )
    assert created.status_code == 201

    res = seeded.delete(f"/api/v1/categories/{cats['常见食材']['id']}")
    assert res.status_code == 409
    assert "食材" in res.json()["error"]["message"]


def test_units_system_cannot_be_deleted(seeded):
    units = {u["name"]: u for u in seeded.get("/api/v1/units").json()["data"]["items"]}
    assert seeded.delete(f"/api/v1/units/{units['克']['id']}").status_code == 409


def test_unit_dimension_filter(seeded):
    q = seeded.get("/api/v1/units", params={"dimension": "quantity"}).json()["data"]["items"]
    assert q and all(u["dimension"] == "quantity" for u in q)


# ---------------------------------------------------------------- 食材


def _units(seeded):
    return {u["symbol"]: u for u in seeded.get("/api/v1/units").json()["data"]["items"]}


def _cats(seeded):
    return {c["name"]: c for c in seeded.get("/api/v1/categories").json()["data"]["items"]}


def _create_chicken(seeded, **over):
    u, c = _units(seeded), _cats(seeded)
    locs = {l["name"]: l for l in seeded.get("/api/v1/storage-locations").json()["data"]["items"]}
    payload = {
        "name": "鸡胸肉",
        "category_id": c["常见食材"]["id"],
        "default_quantity_unit_id": u["包"]["id"],
        "default_weight_unit_id": u["g"]["id"],
        "default_unit_weight": "250",
        "nutrition_basis_amount": "100",
        "nutrition_basis_unit_id": u["g"]["id"],
        "default_storage_location_id": locs["冷冻室"]["id"],
        "minimum_weight": "500",
        "nutrition": [
            {"code": "calories", "value": "165", "basis_amount": "100", "basis_unit_id": u["g"]["id"]}
        ],
        "barcodes": [{"barcode": "6901234567890", "barcode_type": "ean13"}],
    }
    payload.update(over)
    res = seeded.post("/api/v1/ingredients", json=payload)
    return res


def test_create_ingredient_and_detail_fields(seeded):
    res = _create_chicken(seeded)
    assert res.status_code == 201, res.text
    iid = res.json()["data"]["id"]

    d = seeded.get(f"/api/v1/ingredients/{iid}").json()["data"]
    # 验收要求逐项核对
    assert d["name"] == "鸡胸肉"
    assert d["category_path"] == "肉类 · 常见食材"
    assert d["is_active"] is True
    assert d["quantity_unit"]["name"] == "包"
    assert d["weight_unit"]["symbol"] == "g"
    assert d["unit_weight_display"] == "250g"
    assert d["minimum_stock_display"] == "500g"
    assert d["nutrition_basis_display"] == "每100g"
    assert d["location_name"] == "冷冻室"
    assert d["can_convert"] is True
    assert d["nutrition"][0]["code"] == "calories"


def test_conversion_and_refusal(seeded):
    iid = _create_chicken(seeded).json()["data"]["id"]

    ok = seeded.get(f"/api/v1/ingredients/{iid}/conversion", params={"quantity": "2"}).json()["data"]
    assert ok["weight"] == "500"

    # 清空换算关系 → 必须拒绝推算，而不是返回 0 或猜值
    assert seeded.put(f"/api/v1/ingredients/{iid}", json={"default_unit_weight": None}).status_code == 200
    refused = seeded.get(f"/api/v1/ingredients/{iid}/conversion", params={"quantity": "2"})
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "UNIT_NOT_CONVERTIBLE"


def test_conversion_requires_both_units(seeded):
    res = _create_chicken(seeded, name="缺单位", default_quantity_unit_id=None)
    assert res.status_code == 400


def test_wrong_unit_dimension_rejected(seeded):
    u = _units(seeded)
    res = _create_chicken(seeded, name="维度错", default_quantity_unit_id=u["g"]["id"])
    assert res.status_code == 400
    assert "数量" in res.json()["error"]["message"]


def test_duplicate_barcode_conflict(seeded):
    assert _create_chicken(seeded).status_code == 201
    dup = _create_chicken(seeded, name="牛奶")
    assert dup.status_code == 409


def test_search_chinese_pinyin_initials(seeded):
    _create_chicken(seeded)
    for kw in ["鸡", "ji", "jxr", "JIXIONG"]:
        items = seeded.get("/api/v1/ingredients", params={"q": kw}).json()["data"]["items"]
        assert any(i["name"] == "鸡胸肉" for i in items), f"关键词 {kw} 未命中"
    assert seeded.get("/api/v1/ingredients", params={"q": "牛肉"}).json()["data"]["total"] == 0


def test_search_ranks_exact_match_first(seeded):
    _create_chicken(seeded)
    _create_chicken(seeded, name="鸡胸肉丁", barcodes=[])
    items = seeded.get("/api/v1/ingredients", params={"q": "鸡胸肉"}).json()["data"]["items"]
    assert items[0]["name"] == "鸡胸肉"


def test_deactivate_hides_from_default_list(seeded):
    iid = _create_chicken(seeded).json()["data"]["id"]
    assert seeded.post(f"/api/v1/ingredients/{iid}/deactivate").status_code == 200

    default = seeded.get("/api/v1/ingredients").json()["data"]["items"]
    assert all(i["id"] != iid for i in default)

    all_items = seeded.get("/api/v1/ingredients", params={"include_inactive": "true"}).json()["data"]["items"]
    assert any(i["id"] == iid for i in all_items)

    assert seeded.post(f"/api/v1/ingredients/{iid}/activate").status_code == 200
    assert any(i["id"] == iid for i in seeded.get("/api/v1/ingredients").json()["data"]["items"])


def test_parent_category_filter_includes_children(seeded):
    _create_chicken(seeded)
    c = _cats(seeded)
    res = seeded.get("/api/v1/ingredients", params={"category_id": c["肉类"]["id"]}).json()["data"]
    assert res["total"] == 1


# ---------------------------------------------------------------- 图片


def test_upload_image_and_attach(seeded):
    up = seeded.post("/api/v1/files/upload", files={"file": ("a.png", PNG_1PX, "image/png")})
    assert up.status_code == 201, up.text
    asset = up.json()["data"]

    raw = seeded.get(f"/api/v1/files/{asset['id']}/raw")
    assert raw.status_code == 200
    assert raw.headers["content-type"].startswith("image/png")

    iid = _create_chicken(seeded).json()["data"]["id"]
    assert seeded.put(f"/api/v1/ingredients/{iid}", json={"image_asset_id": asset["id"]}).status_code == 200
    d = seeded.get(f"/api/v1/ingredients/{iid}").json()["data"]
    assert d["image_url"].endswith(f"/files/{asset['id']}/raw")

    # 被引用的图片不允许删除
    assert seeded.delete(f"/api/v1/files/{asset['id']}").status_code == 409


def test_non_image_rejected(seeded):
    res = seeded.post("/api/v1/files/upload", files={"file": ("x.txt", b"hello", "text/plain")})
    assert res.status_code == 415


def test_same_image_deduplicated(seeded):
    a = seeded.post("/api/v1/files/upload", files={"file": ("a.png", PNG_1PX, "image/png")}).json()["data"]
    b = seeded.post("/api/v1/files/upload", files={"file": ("b.png", PNG_1PX, "image/png")}).json()["data"]
    assert a["id"] == b["id"], "相同内容应复用同一 file_asset"


# ---------------------------------------------------------------- 条码


def test_barcode_bind_lookup_unbind(seeded):
    iid = _create_chicken(seeded).json()["data"]["id"]

    look = seeded.get("/api/v1/barcodes/6901234567890")
    assert look.status_code == 200
    assert look.json()["data"]["ingredient"]["id"] == iid

    assert seeded.get("/api/v1/barcodes/0000000000000").status_code == 404

    bind = seeded.post(
        "/api/v1/barcodes", json={"ingredient_id": iid, "barcode": "1234567890123", "barcode_type": "ean13"}
    )
    assert bind.status_code == 201
    bid = bind.json()["data"]["id"]
    assert seeded.delete(f"/api/v1/barcodes/{bid}").status_code == 200


def test_barcode_conflict_on_second_ingredient(seeded):
    _create_chicken(seeded)
    other = _create_chicken(seeded, name="牛肉", barcodes=[]).json()["data"]["id"]
    res = seeded.post(
        "/api/v1/barcodes", json={"ingredient_id": other, "barcode": "6901234567890", "barcode_type": "ean13"}
    )
    assert res.status_code == 409
