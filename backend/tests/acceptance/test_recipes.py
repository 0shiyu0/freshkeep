"""阶段 8（下）验收：菜谱管理 / 库存匹配 / 多菜谱合并采购清单。

口径：
- 菜谱需求以**重量**为主；只填数量且食材有 `default_unit_weight` 时换算，否则该行标 `unmeasured`；
- 匹配 = 需求（按份数缩放）− 当前库存（`v_inventory.total_weight`），缺口为负取 0；
- 合并采购清单：同一食材跨菜谱**需求相加**后再减库存，只保留仍有缺口的行；
- 清单落库 `shopping_lists` / `shopping_list_items(source='recipe')`，不触发任何库存变动。
"""
from __future__ import annotations

from decimal import Decimal
import uuid

import pytest


@pytest.fixture()
def ing(seeded):
    """鸡胸肉（500g 库存）、牛奶（200g 库存，无数量换算）。"""
    from decimal import Decimal as D

    from app.db.session import SessionLocal
    from app.models import Ingredient, Unit

    with SessionLocal() as db:
        g = db.query(Unit).filter_by(symbol="g").first()
        gid = str(g.id)
        pack = db.query(Unit).filter_by(name="包").first()
        pid = str(pack.id) if pack else gid

    a = seeded.post("/api/v1/ingredients", json={"name": "鸡胸肉", "default_weight_unit_id": gid}).json()["data"]["id"]
    b = seeded.post("/api/v1/ingredients", json={"name": "牛奶", "default_weight_unit_id": gid}).json()["data"]["id"]
    # 鸡胸肉 500g
    seeded.post("/api/v1/batches", json={"ingredient_id": a, "weight": "500", "purchase_cost": "18.00"})
    # 牛奶 200g
    seeded.post("/api/v1/batches", json={"ingredient_id": b, "weight": "200", "purchase_cost": "6.00"})
    return {"chicken": a, "milk": b, "g_id": gid, "pack_id": pid}


def _create(client, name: str, items: list[dict], servings: str = "1") -> dict:
    r = client.post("/api/v1/recipes", json={
        "name": name, "servings": servings, "steps": "1. 洗净\n2. 下锅", "items": items,
    })
    assert r.status_code == 201, r.text
    return r.json()["data"]


# ---------------------------------------------------------------- 8.11 管理


def test_create_and_detail(seeded, ing):
    recipe = _create(seeded, "鸡胸肉沙拉", [
        {"ingredient_id": ing["chicken"], "weight": "200"},
        {"ingredient_id": ing["milk"], "weight": "100", "note": "调味"},
    ])
    assert recipe["name"] == "鸡胸肉沙拉"
    assert len(recipe["items"]) == 2
    assert recipe["servings"] == "1.00"

    d = seeded.get(f"/api/v1/recipes/{recipe['id']}").json()["data"]
    names = {i["ingredient_name"] for i in d["items"]}
    assert names == {"鸡胸肉", "牛奶"}
    # 详情带当前库存，便于直接展示
    chicken = next(i for i in d["items"] if i["ingredient_name"] == "鸡胸肉")
    assert Decimal(chicken["available_weight"]) == Decimal("500.000")


def test_create_validation(seeded, ing):
    r = seeded.post("/api/v1/recipes", json={"name": "", "items": [{"ingredient_id": ing["chicken"], "weight": "1"}]})
    assert r.status_code == 400
    r2 = seeded.post("/api/v1/recipes", json={"name": "无食材", "items": []})
    assert r2.status_code == 400
    r3 = seeded.post("/api/v1/recipes", json={"name": "缺量", "items": [{"ingredient_id": ing["chicken"]}]})
    assert r3.status_code == 400
    r4 = seeded.post("/api/v1/recipes", json={
        "name": "未知食材", "items": [{"ingredient_id": str(uuid.uuid4()), "weight": "1"}],
    })
    assert r4.status_code == 404


def test_update_replaces_items(seeded, ing):
    recipe = _create(seeded, "可改菜谱", [{"ingredient_id": ing["chicken"], "weight": "200"}])
    r = seeded.put(f"/api/v1/recipes/{recipe['id']}", json={
        "name": "改名菜谱", "servings": "2",
        "items": [{"ingredient_id": ing["milk"], "weight": "150"}],
    })
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["name"] == "改名菜谱"
    assert len(d["items"]) == 1
    assert d["items"][0]["ingredient_name"] == "牛奶"


def test_delete(seeded, ing):
    recipe = _create(seeded, "待删菜谱", [{"ingredient_id": ing["chicken"], "weight": "100"}])
    assert seeded.delete(f"/api/v1/recipes/{recipe['id']}").status_code == 200
    assert seeded.get(f"/api/v1/recipes/{recipe['id']}").status_code == 404


def test_list_with_search(seeded, ing):
    _create(seeded, "番茄炒蛋", [{"ingredient_id": ing["chicken"], "weight": "100"}])
    _create(seeded, "牛奶布丁", [{"ingredient_id": ing["milk"], "weight": "100"}])
    all_rows = seeded.get("/api/v1/recipes").json()["data"]
    assert all_rows["total"] == 2
    hit = seeded.get("/api/v1/recipes", params={"q": "牛奶"}).json()["data"]
    assert hit["total"] == 1 and hit["items"][0]["name"] == "牛奶布丁"


# ---------------------------------------------------------------- 8.12 匹配


def test_match_enough_stock(seeded, ing):
    recipe = _create(seeded, "够做", [{"ingredient_id": ing["chicken"], "weight": "300"}])
    d = seeded.get(f"/api/v1/recipes/{recipe['id']}/match").json()["data"]
    assert d["can_cook"] is True
    assert d["missing_count"] == 0
    row = d["items"][0]
    assert Decimal(row["required_weight"]) == Decimal("300.000")
    assert Decimal(row["available_weight"]) == Decimal("500.000")
    assert Decimal(row["shortage_weight"]) == 0


def test_match_shortage(seeded, ing):
    recipe = _create(seeded, "不够做", [
        {"ingredient_id": ing["chicken"], "weight": "800"},
        {"ingredient_id": ing["milk"], "weight": "100"},
    ])
    d = seeded.get(f"/api/v1/recipes/{recipe['id']}/match").json()["data"]
    assert d["can_cook"] is False
    assert d["missing_count"] == 1
    chicken = next(i for i in d["items"] if i["ingredient_name"] == "鸡胸肉")
    assert Decimal(chicken["shortage_weight"]) == Decimal("300.000")  # 800 - 500


def test_match_scales_with_servings(seeded, ing):
    """菜谱基准 1 份需 300g；做 2 份需 600g，库存 500 → 缺 100。"""
    recipe = _create(seeded, "按份缩放", [{"ingredient_id": ing["chicken"], "weight": "300"}], servings="1")
    d = seeded.get(f"/api/v1/recipes/{recipe['id']}/match", params={"servings": "2"}).json()["data"]
    row = d["items"][0]
    assert Decimal(row["required_weight"]) == Decimal("600.000")
    assert Decimal(row["shortage_weight"]) == Decimal("100.000")


def test_match_quantity_only_marks_unmeasured(seeded, ing):
    """只填数量且无换算关系 → 不参与重量匹配，标 unmeasured。"""
    recipe = _create(seeded, "按数量", [{"ingredient_id": ing["milk"], "quantity": "2"}])
    d = seeded.get(f"/api/v1/recipes/{recipe['id']}/match").json()["data"]
    row = d["items"][0]
    assert row["unmeasured"] is True
    assert Decimal(row["required_weight"]) == 0


# ---------------------------------------------------------------- 8.13 采购清单


def test_shopping_list_merges_recipes(seeded, ing):
    """两个菜谱都要鸡胸肉：需求相加后减库存；牛奶无缺口不出现。"""
    r1 = _create(seeded, "菜谱A", [
        {"ingredient_id": ing["chicken"], "weight": "400"},
        {"ingredient_id": ing["milk"], "weight": "50"},
    ])
    r2 = _create(seeded, "菜谱B", [
        {"ingredient_id": ing["chicken"], "weight": "300"},
        {"ingredient_id": ing["milk"], "weight": "50"},
    ])
    r = seeded.post("/api/v1/shopping-lists/from-recipes", json={
        "recipe_ids": [r1["id"], r2["id"]], "name": "本周采购",
    })
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    # 鸡胸肉 400+300=700，库存 500 → 缺 200；牛奶 100 < 200 无缺口
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["ingredient_name"] == "鸡胸肉"
    assert Decimal(item["suggested_weight"]) == Decimal("200.000")
    assert item["source"] == "recipe"

    # 落库且不产生库存变动
    from sqlalchemy import text

    from app.db.session import SessionLocal

    with SessionLocal() as db:
        lists = db.execute(text("select count(*) from shopping_lists")).scalar()
        items = db.execute(text("select count(*) from shopping_list_items where source='recipe'")).scalar()
        tx = db.execute(text("select count(*) from inventory_transactions")).scalar()
    assert lists == 1 and items == 1 and tx == 2  # 只有两次入库


def test_shopping_list_with_servings_override(seeded, ing):
    r1 = _create(seeded, "单人份", [{"ingredient_id": ing["chicken"], "weight": "200"}], servings="1")
    r = seeded.post("/api/v1/shopping-lists/from-recipes", json={
        "recipe_ids": [r1["id"]], "servings_map": {r1["id"]: "3"},
    }).json()["data"]
    # 3 份需 600，库存 500 → 缺 100
    assert Decimal(r["items"][0]["suggested_weight"]) == Decimal("100.000")


def test_shopping_list_all_sufficient(seeded, ing):
    r1 = _create(seeded, "库存充足", [{"ingredient_id": ing["chicken"], "weight": "100"}])
    d = seeded.post("/api/v1/shopping-lists/from-recipes", json={"recipe_ids": [r1["id"]]}).json()["data"]
    assert d["items"] == []
    assert d["message"] or d["name"]


def test_shopping_list_endpoints(seeded, ing):
    r1 = _create(seeded, "清单菜谱", [{"ingredient_id": ing["chicken"], "weight": "900"}])
    created = seeded.post("/api/v1/shopping-lists/from-recipes", json={"recipe_ids": [r1["id"]], "name": "测试清单"}).json()["data"]

    listed = seeded.get("/api/v1/shopping-lists").json()["data"]
    assert listed["total"] == 1
    assert listed["items"][0]["name"] == "测试清单"

    detail = seeded.get(f"/api/v1/shopping-lists/{created['id']}").json()["data"]
    assert detail["status"] == "open"
    assert len(detail["items"]) == 1


def test_recipes_require_login(client):
    assert client.get("/api/v1/recipes").status_code == 401
    assert client.get("/api/v1/shopping-lists").status_code == 401
