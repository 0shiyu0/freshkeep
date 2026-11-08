"""pytest 共享夹具。

策略：所有接口测试跑在**真实 PostgreSQL** 的独立库 `freshkeep_test` 上
（AGENTS.md §7 明令禁止用 SQLite 跑测试，因为无 NUMERIC、无行锁会掩盖缺陷）。

- 首次运行自动建库 + 执行 database/001_init.sql + 写入基础字典
- 每个用例前清空业务数据（保留字典），保证互不污染
- 数据库不可用时整套 api 测试跳过，而不是假绿
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

TEST_DB = os.environ.get("TEST_DB_NAME", "freshkeep_test")
# conftest 位于 backend/tests/，仓库根是 parents[2]
ROOT = Path(__file__).resolve().parents[2]


def _base_url() -> str:
    """测试库连接串：默认用本机 PG（用户名为当前登录用户、无密码）。"""
    if os.environ.get("TEST_DATABASE_URL"):
        return os.environ["TEST_DATABASE_URL"]
    user = os.environ.get("USER", "postgres")
    return f"postgresql+psycopg://{user}@127.0.0.1:5432/{TEST_DB}"


def _can_connect() -> bool:
    from sqlalchemy import create_engine, text

    try:
        eng = create_engine(_base_url().replace(f"/{TEST_DB}", "/postgres"), connect_args={"connect_timeout": 3})
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="session", autouse=True)
def _prepare_db():
    """建测试库并应用 DDL（幂等）。不可连接则跳过 api 测试模块。"""
    if not _can_connect():
        yield False
        return

    from sqlalchemy import create_engine, text

    admin_url = _base_url().replace(f"/{TEST_DB}", "/postgres")
    eng = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        exists = c.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": TEST_DB}).first()
        if not exists:
            c.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    eng.dispose()

    os.environ["DATABASE_URL"] = _base_url()

    # 每次都从干净 schema 开始：测试库是消耗品，避免上一次残留导致 DuplicateTable
    ddl = (ROOT / "database" / "001_init.sql").read_text(encoding="utf-8")
    eng = create_engine(_base_url(), isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        c.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    eng.dispose()

    eng = create_engine(_base_url())
    # 001 自带 BEGIN/COMMIT，整份执行即可
    with eng.connect() as c:
        c.exec_driver_sql(ddl)
    # alembic 基线：让 /system/db 能读到迁移版本
    with eng.begin() as c:
        c.execute(
            text("CREATE TABLE IF NOT EXISTS alembic_version (version_num varchar(32) NOT NULL PRIMARY KEY)")
        )
        c.execute(text("DELETE FROM alembic_version"))
        c.execute(text("INSERT INTO alembic_version VALUES ('0001_init')"))
    eng.dispose()

    yield True


@pytest.fixture(scope="session")
def db_ready(_prepare_db):
    if not _prepare_db:
        pytest.skip("本机没有可用的 PostgreSQL（且未设置 TEST_DATABASE_URL），跳过接口测试")
    return True


@pytest.fixture(scope="session")
def app_module(db_ready):
    """在 DATABASE_URL 指向测试库之后才导入 app，避免 engine 指向生产库。"""
    import importlib

    import app.main as m

    importlib.reload(m)
    return m


@pytest.fixture()
def client(app_module):
    from fastapi.testclient import TestClient

    return TestClient(app_module.app)


@pytest.fixture()
def clean_db(db_ready):
    """每个用例前清空业务数据；字典（单位/分类/位置/营养）与 owner 保留。"""
    from sqlalchemy import text

    from app.db.session import engine

    with engine.begin() as c:
        c.execute(
            text(
                "TRUNCATE consumption_nutrition, consumption_records, transaction_allocations, "
                "inventory_transactions, batches, ingredient_barcodes, ingredient_nutrition, "
                "ingredients, shopping_list_items, shopping_lists, recipe_items, recipes, "
                "notifications, file_assets, idempotency_keys RESTART IDENTITY CASCADE"
            )
        )
        c.execute(text("UPDATE users SET password_hash = NULL"))
        c.execute(text("DELETE FROM devices"))
        c.execute(text("DELETE FROM pair_codes"))
    yield


@pytest.fixture()
def auth_client(client, clean_db):
    """已登录的客户端：用配对码换 Cookie（Web 通道）。"""
    from app.services.auth import get_owner, issue_pair_code

    from app.db.session import SessionLocal

    with SessionLocal() as db:
        get_owner(db)
        code = issue_pair_code(db)
        db.commit()

    res = client.post(
        "/api/v1/auth/pair",
        json={"code": code, "device_name": "pytest", "platform": "web"},
    )
    assert res.status_code == 200, res.text
    return client


@pytest.fixture()
def seeded(auth_client):
    """建一套最小可用字典（单位/分类/位置/营养项目）。"""
    from app.cli import CATEGORIES, LOCATIONS, NUTRITION, UNITS
    from app.db.session import SessionLocal
    from app.models import Category, NutritionDefinition, StorageLocation, Unit

    with SessionLocal() as db:
        for name, symbol, dim, prec, system in UNITS:
            if not db.query(Unit).filter_by(name=name).first():
                db.add(Unit(name=name, symbol=symbol, dimension=dim, precision=prec, is_system=system))
        for code, name, unit, order in NUTRITION:
            if not db.query(NutritionDefinition).filter_by(code=code).first():
                db.add(NutritionDefinition(code=code, name=name, unit=unit, sort_order=order))
        for idx, (name, desc) in enumerate(LOCATIONS):
            if not db.query(StorageLocation).filter_by(name=name).first():
                db.add(StorageLocation(name=name, description=desc, sort_order=idx))
        db.flush()
        for order, (name, children) in enumerate(CATEGORIES):
            parent = db.query(Category).filter_by(name=name, parent_id=None).first()
            if not parent:
                parent = Category(name=name, sort_order=order)
                db.add(parent)
                db.flush()
            for c_order, child in enumerate(children):
                if not db.query(Category).filter_by(name=child).first():
                    db.add(Category(name=child, parent_id=parent.id, sort_order=c_order))
        db.commit()

    return auth_client
