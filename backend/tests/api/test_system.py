"""系统接口测试：健康检查、请求 id、信封结构、前端日志上报。

注意：所有用例都通过 `client` 夹具取 TestClient，**不在模块层 import app.main**，
否则 engine 会在 conftest 设置测试库之前就绑定到默认库。
"""
from __future__ import annotations

from pathlib import Path


def _alembic_head() -> str:
    """与生产一致的迁移版本：动态读 head，避免测试与迁移漂移。"""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = Path(__file__).resolve().parents[3]
    cfg = Config(str(root / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "backend" / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head() or ""

def test_api_health_uses_envelope(client, clean_db):
    res = client.get("/api/v1/health")
    assert res.status_code in {200, 503}
    body = res.json()
    assert body["success"] is True
    assert "request_id" in body
    assert body["data"]["version"]


def test_ping_identifies_service(client, clean_db):
    res = client.get("/api/v1/ping")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["name"] == "freshkeep"
    assert data["api"] == 1
    assert "server_time" in data


def test_system_db_reports_structure(client, clean_db):
    body = client.get("/api/v1/system/db").json()
    assert body["success"] is True
    data = body["data"]
    assert data["connected"] is True
    assert data["tables"] == 27          # 业务表数（不含 alembic_version）；0003 recognition_drafts + 0004 recipe_steps
    assert data["migration"] == _alembic_head()
    assert data["pool"]["max_overflow"] >= 0


def test_request_id_propagated(client, clean_db):
    res = client.get("/api/v1/ping")
    rid = res.headers.get("X-Request-Id", "")
    assert len(rid) == 32
    assert all(c in "0123456789abcdef" for c in rid)
    assert res.json()["request_id"] == rid


def test_client_can_post_error_logs(client, clean_db):
    res = client.post(
        "/api/v1/system/client-logs",
        json={"entries": [{"scope": "test", "message": "self-check"}]},
    )
    assert res.status_code == 202
    assert res.json()["data"]["received"] == 1


def test_unknown_api_path_returns_json_404(client, clean_db):
    res = client.get("/api/v1/not-implemented-yet")
    assert res.status_code in {404, 405}
    body = res.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"
