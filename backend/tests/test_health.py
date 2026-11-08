"""接口冒烟测试。

约定：`/api/v1/*` 一律返回 `{success, data, message, request_id}` 信封；
根路径 `/health` 是给容器探针用的裸响应（不含信封），两者都要覆盖。
测试不假设库中已有数据，只校验结构与状态码。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_health_for_probe_is_raw():
    """/health 供 docker/k8s 探针使用，保持裸对象，避免探针解析信封。"""
    res = client.get("/health")
    assert res.status_code in {200, 503}
    body = res.json()
    assert body["status"] in {"ok", "degraded"}
    assert isinstance(body["db"], bool)


def test_api_health_uses_envelope():
    res = client.get("/api/v1/health")
    assert res.status_code in {200, 503}
    body = res.json()
    assert body["success"] is True
    assert "request_id" in body
    assert body["data"]["version"]


def test_ping_uses_envelope_and_identifies_service():
    res = client.get("/api/v1/ping")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    data = body["data"]
    assert data["name"] == "freshkeep"
    assert data["api"] == 1
    assert "server_time" in data


def test_system_db_reports_pool_and_tables():
    res = client.get("/api/v1/system/db")
    body = res.json()
    assert body["success"] is True
    data = body["data"]
    assert "connected" in data
    if data["connected"]:
        # 连上库时应能读到版本与连接池配置；表数取决于是否已迁移，不硬编码
        assert data["server_version"]
        assert data["pool"]["max_overflow"] >= 0


def test_request_id_header_is_present_and_propagated():
    res = client.get("/api/v1/ping")
    rid = res.headers.get("X-Request-Id", "")
    assert len(rid) == 32
    assert all(c in "0123456789abcdef" for c in rid)
    # 响应体里的 request_id 必须与响应头一致，否则日志无法串联
    assert res.json()["request_id"] == rid


def test_client_can_post_error_logs():
    res = client.post(
        "/api/v1/system/client-logs",
        json={"entries": [{"scope": "test", "message": "self-check"}]},
    )
    assert res.status_code == 202
    assert res.json()["data"]["received"] == 1


def test_unknown_api_path_returns_404_not_html():
    """/api 下未实现的路径必须是 404，不能被静态托管兜成 index.html。"""
    res = client.get("/api/v1/not-implemented-yet")
    assert res.status_code in {404, 405}
    assert res.json()["success"] is False
    assert res.json()["error"]["code"] == "NOT_FOUND"
