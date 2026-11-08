"""接口冒烟测试：不依赖数据库（DB 不可用时 /health 返回 degraded，属预期）。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_200_and_reports_db_state():
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] in {"ok", "degraded"}
    assert isinstance(body["db"], bool)
    assert body["version"]


def test_ping_identifies_service_and_api_version():
    res = client.get("/api/v1/ping")
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "freshkeep"
    assert body["api"] == 1
    assert "server_time" in body


def test_request_id_header_is_present_and_stable_length():
    res = client.get("/health")
    rid = res.headers.get("X-Request-Id", "")
    assert len(rid) == 32
    assert all(c in "0123456789abcdef" for c in rid)


def test_unknown_api_path_returns_404_not_html():
    """/api 下未实现的路径必须是 404，不能被静态托管兜成 index.html。"""
    res = client.get("/api/v1/not-implemented-yet")
    assert res.status_code in {404, 405}
