"""M7 验收：备份 / CSV 导出 / 定时任务 / 采购清单增强。

备份用纯 Python 逻辑导出（tar.gz：schema.sql + 每表 CSV + manifest），
不依赖 pg_dump；测试把 `backup_dir` 指到临时目录，避免污染仓库。
"""
from __future__ import annotations

import io
import tarfile
from decimal import Decimal

import pytest


@pytest.fixture()
def backup_dir():
    """settings 是 frozen dataclass，用 object.__setattr__ 临时覆盖。

    不用 pytest 的 tmp_path：本机沙箱禁止在系统临时目录建目录，
    改用 backend/.pytest-backups/<uuid>（已加入 .gitignore）。
    """
    import shutil
    import uuid
    from pathlib import Path

    from app.core.config import settings

    original = settings.backup_dir
    tmp = Path(__file__).resolve().parents[2] / ".pytest-backups" / uuid.uuid4().hex
    tmp.mkdir(parents=True, exist_ok=True)
    object.__setattr__(settings, "backup_dir", tmp)
    yield tmp
    object.__setattr__(settings, "backup_dir", original)
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture()
def ing(seeded):
    from app.db.session import SessionLocal
    from app.models import Ingredient, Unit

    with SessionLocal() as db:
        g = db.query(Unit).filter_by(symbol="g").first()
        gid = str(g.id)
    rid = seeded.post("/api/v1/ingredients", json={
        "name": "鸡胸肉", "default_weight_unit_id": gid, "minimum_weight": "1000",
    }).json()["data"]["id"]
    seeded.post("/api/v1/batches", json={"ingredient_id": rid, "weight": "500", "purchase_cost": "18.00"})
    return {"id": rid, "g_id": gid}


# ---------------------------------------------------------------- 备份


def test_create_backup_and_manifest(seeded, ing, backup_dir):
    r = seeded.post("/api/v1/backup")
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert data["name"].startswith("freshkeep-backup-") and data["name"].endswith(".tar.gz")
    assert data["tables"] == 27
    assert data["total_rows"] > 0
    assert len(data["sha256"]) == 64

    path = backup_dir / data["name"]
    assert path.exists() and path.stat().st_size > 0
    with tarfile.open(path, "r:gz") as tar:
        names = set(tar.getnames())
        assert "schema.sql" in names and "manifest.json" in names
        assert "tables/ingredients.csv" in names
        assert "tables/recipe_steps.csv" in names
        manifest = tar.extractfile("manifest.json").read().decode()
        assert '"format": "logical-csv-v1"' in manifest
        csv = tar.extractfile("tables/batches.csv").read().decode()
    assert csv.startswith("id,") or "ingredient_id" in csv.splitlines()[0]


def test_backup_list_verify_download(seeded, ing, backup_dir):
    created = seeded.post("/api/v1/backup").json()["data"]["name"]

    listed = seeded.get("/api/v1/backups").json()["data"]
    assert listed["total"] == 1 and listed["items"][0]["name"] == created

    ver = seeded.post(f"/api/v1/backups/{created}/verify").json()["data"]
    assert ver["ok"] is True and ver["tables"] == 27 and ver["missing"] == []

    dl = seeded.get(f"/api/v1/backups/{created}/download")
    assert dl.status_code == 200
    assert dl.headers["content-type"].startswith("application/gzip")
    assert len(dl.content) > 100


def test_backup_path_traversal_rejected(seeded, backup_dir):
    r = seeded.get("/api/v1/backups/..%2Fsecret.tar.gz/download")
    assert r.status_code in (400, 404)
    r2 = seeded.post("/api/v1/backups/not-exist.tar.gz/verify")
    assert r2.status_code == 404


def test_backup_does_not_change_inventory(seeded, ing, backup_dir):
    from sqlalchemy import text

    from app.db.session import SessionLocal

    def snapshot():
        with SessionLocal() as db:
            return (
                db.execute(text("select count(*) from batches")).scalar(),
                db.execute(text("select count(*) from inventory_transactions")).scalar(),
            )

    before = snapshot()
    seeded.post("/api/v1/backup")
    assert snapshot() == before


# ---------------------------------------------------------------- CSV 导出


def test_export_transactions_csv(seeded, ing):
    seeded.post("/api/v1/consumptions", json={"ingredient_id": ing["id"], "weight": "100"})
    r = seeded.get("/api/v1/export/transactions.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    body = r.content
    assert body.startswith("\ufeff".encode()), "必须带 BOM 便于 Excel"
    text_body = body.decode("utf-8-sig")
    lines = [ln for ln in text_body.splitlines() if ln]
    assert lines[0].startswith("transaction_no,type,ingredient_name")
    assert len(lines) == 3  # 表头 + 入库 + 消耗


def test_export_consumptions_csv(seeded, ing):
    seeded.post("/api/v1/consumptions", json={"ingredient_id": ing["id"], "weight": "100"})
    r = seeded.get("/api/v1/export/consumptions.csv")
    assert r.status_code == 200
    lines = [ln for ln in r.content.decode("utf-8-sig").splitlines() if ln]
    assert lines[0].startswith("consumption_no,ingredient_name")
    assert "CS-" in lines[1]


def test_export_unknown_kind(seeded):
    assert seeded.get("/api/v1/export/whatever.csv").status_code == 404


# ---------------------------------------------------------------- 定时任务


def test_tasks_status_and_manual_run(seeded):
    st = seeded.get("/api/v1/tasks").json()["data"]
    assert st["enabled"] is False          # 测试环境默认关闭
    assert len(st["jobs"]) == 3
    assert {j["id"] for j in st["jobs"]} == {"daily_reconcile", "daily_backup", "expiring_scan"}

    r = seeded.post("/api/v1/tasks/expiring_scan/run")
    assert r.status_code == 200, r.text
    assert "created" in r.json()["data"]

    from sqlalchemy import text

    from app.db.session import SessionLocal

    with SessionLocal() as db:
        n = db.execute(text("select count(*) from audit_logs where action='scheduler_scan'")).scalar()
    assert n >= 1


def test_manual_run_unknown_job(seeded):
    assert seeded.post("/api/v1/tasks/unknown/run").status_code == 400


def test_reconcile_job_repairs_cache(seeded, ing):
    """人为制造缓存差异后，对账作业应修复并写审计。"""
    from sqlalchemy import text

    from app.db.session import SessionLocal

    bid = seeded.get("/api/v1/batches", params={"ingredient_id": ing["id"]}).json()["data"]["items"][0]["id"]
    with SessionLocal() as db:
        db.execute(text("update batches set remaining_weight = remaining_weight - 5 where id=CAST(:b AS uuid)"),
                   {"b": bid})
        db.commit()

    r = seeded.post("/api/v1/tasks/daily_reconcile/run")
    assert r.status_code == 200
    assert r.json()["data"]["repaired"] == 1
    left = seeded.get(f"/api/v1/batches/{bid}").json()["data"]["remaining_weight"]
    assert Decimal(left) == Decimal("500.000")
    with SessionLocal() as db:
        n = db.execute(text("select count(*) from audit_logs where action='scheduler_reconcile'")).scalar()
    assert n >= 1


# ---------------------------------------------------------------- 清单增强


def _list_with_item(seeded, ing) -> tuple[str, str]:
    r = seeded.post("/api/v1/shopping-lists/from-low-stock", json={})
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert data["items"], "低库存应生成至少一项"
    assert data["items"][0]["source"] == "low_stock"
    detail = seeded.get(f"/api/v1/shopping-lists/{data['id']}").json()["data"]
    return data["id"], detail["items"][0]["id"]


def test_low_stock_shopping_list(seeded, ing):
    lid, item_id = _list_with_item(seeded, ing)
    detail = seeded.get(f"/api/v1/shopping-lists/{lid}").json()["data"]
    assert Decimal(detail["items"][0]["suggested_weight"]) == Decimal("500.000")  # 1000 - 500


def test_tick_item_and_complete_list(seeded, ing):
    lid, item_id = _list_with_item(seeded, ing)

    r = seeded.patch(f"/api/v1/shopping-list-items/{item_id}", json={"is_completed": True})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["is_completed"] is True

    done = seeded.post(f"/api/v1/shopping-lists/{lid}/complete").json()["data"]
    assert done["status"] == "completed"
    detail = seeded.get(f"/api/v1/shopping-lists/{lid}").json()["data"]
    assert detail["status"] == "completed"
    assert all(i["is_completed"] for i in detail["items"])


def test_shopping_endpoints_require_login(client):
    assert client.get("/api/v1/backups").status_code == 401
    assert client.get("/api/v1/tasks").status_code == 401
