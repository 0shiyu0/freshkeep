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


def _low_stock_list(seeded, ing) -> str:
    """为食材设置最低库存并按建议生成采购清单。"""
    r = seeded.put(f"/api/v1/ingredients/{ing['chicken']}", json={"minimum_weight": "1000"})
    assert r.status_code == 200, r.text
    r = seeded.post("/api/v1/shopping-lists/from-low-stock", json={})
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


def psql_count(table: str) -> str:
    from sqlalchemy import text

    from app.db.session import SessionLocal

    with SessionLocal() as db:
        return db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()


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


# ---------------------------------------------------------------- 结构化步骤


def test_structured_steps(seeded, ing):
    """数组形式写入：顺序、文本、单步时长都要保留。"""
    r = seeded.post("/api/v1/recipes", json={
        "name": "结构化步骤",
        "items": [{"ingredient_id": ing["chicken"], "weight": "100"}],
        "steps": [
            {"text": "腌 10 分钟", "duration_minutes": 10},
            {"text": "中火煎 6 分钟", "duration_minutes": 6},
        ],
    })
    assert r.status_code == 201, r.text
    d = r.json()["data"]
    assert [s["text"] for s in d["steps"]] == ["腌 10 分钟", "中火煎 6 分钟"]
    assert [s["duration_minutes"] for s in d["steps"]] == [10, 6]
    assert d["steps"][0]["legacy"] is False
    assert d["steps_text"] == "腌 10 分钟\n中火煎 6 分钟"


def test_text_steps_are_parsed_and_stripped(seeded, ing):
    """旧式字符串：按行拆分并去掉序号前缀。"""
    d = _create(seeded, "字符串步骤", [{"ingredient_id": ing["chicken"], "weight": "100"}])
    # _create 传的是 "1. 洗净\n2. 下锅"
    assert [s["text"] for s in d["steps"]] == ["洗净", "下锅"]
    assert len(d["steps"]) == 2


def test_legacy_text_fallback(seeded, ing):
    """库里只有 recipes.steps 旧文本、没有步骤行时，详情按行兜底并标 legacy。"""
    from sqlalchemy import text

    from app.db.session import SessionLocal

    d = _create(seeded, "旧数据菜谱", [{"ingredient_id": ing["chicken"], "weight": "100"}])
    rid = d["id"]
    with SessionLocal() as db:
        db.execute(text("delete from recipe_steps where recipe_id = CAST(:r AS uuid)"), {"r": rid})
        db.execute(text("update recipes set steps = '甲\n乙' where id = CAST(:r AS uuid)"), {"r": rid})
        db.commit()

    got = seeded.get(f"/api/v1/recipes/{rid}").json()["data"]
    assert [s["text"] for s in got["steps"]] == ["甲", "乙"]
    assert all(s["legacy"] is True for s in got["steps"])


# ---------------------------------------------------------------- 一键入库


def test_import_shopping_list_creates_batches(seeded, ing):
    """阶段 9 后续：清单一键入库 —— 每项生成批次（成本按最近单价估算），清单自动完成。"""
    # ing fixture 已造 500g 批次（单价 0.036/g）；建议 = 最低 1000 - 现有 500
    lid = _low_stock_list(seeded, ing)
    item_id = seeded.get(f"/api/v1/shopping-lists/{lid}").json()["data"]["items"][0]["id"]

    tx_before = Decimal(psql_count("inventory_transactions"))
    batches_before = Decimal(psql_count("batches"))

    r = seeded.post(f"/api/v1/shopping-lists/{lid}/import")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert len(data["batches"]) == 1
    assert Decimal(data["batches"][0]["weight"]) == Decimal("500.000")
    assert Decimal(data["total_cost"]) == Decimal("18.00")   # 最近单价 0.036 × 500

    # 库存按五步事务增长：批次 +1、流水 +1
    assert Decimal(psql_count("batches")) == batches_before + 1
    assert Decimal(psql_count("inventory_transactions")) == tx_before + 1
    row = seeded.get(f"/api/v1/batches/{data['batches'][0]['batch_id']}").json()["data"]
    assert row["initial_weight"] == "500.000"

    # 清单自动完成
    detail = seeded.get(f"/api/v1/shopping-lists/{lid}").json()["data"]
    assert detail["status"] == "completed"

    # 清单为空项时不允许重复导入
    r2 = seeded.post(f"/api/v1/shopping-lists/{lid}/import")
    assert r2.status_code == 409
