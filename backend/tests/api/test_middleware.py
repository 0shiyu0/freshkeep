"""中间件测试：网段白名单与写操作幂等。

对应 docs/DEVELOPMENT_PLAN.md 的 M0 剩余项，也是 API 契约 §1.4 与 §9 的要求。
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------- CIDR


def test_cidr_allows_loopback_and_test_client(client, clean_db):
    """本机回环与测试客户端应放行；否则本地开发与 CI 都跑不起来。"""
    assert client.get("/api/v1/ping").status_code == 200


@pytest.mark.parametrize(
    "ip,expected",
    [
        ("127.0.0.1", True),        # 回环
        ("192.168.31.10", True),    # 默认白名单内
        ("10.1.2.3", True),         # 默认白名单内
        ("100.64.5.6", True),       # 组网网段
        ("8.8.8.8", False),         # 公网
        ("1.1.1.1", False),
        ("testclient", True),       # 非 IP，视为本地
    ],
)
def test_cidr_decision_matrix(ip, expected):
    from app.core.middleware import CidrMiddleware

    mw = CidrMiddleware(app=None)
    assert mw._allowed(ip) is expected


def test_cidr_rejects_public_ip_through_asgi():
    """真实走一遍 ASGI：公网来源必须拿到 403 且是统一信封结构。"""
    from app.core.middleware import CidrMiddleware

    captured = {}

    async def fake_app(scope, receive, send):   # 不应被调用
        captured["called"] = True

    async def send(message):
        if message["type"] == "http.response.start":
            captured["status"] = message["status"]
        elif message["type"] == "http.response.body":
            captured["body"] = message.get("body", b"")

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {"type": "http", "method": "GET", "path": "/api/v1/ping", "headers": [], "client": ("8.8.8.8", 1234)}

    import asyncio

    asyncio.run(CidrMiddleware(fake_app)(scope, receive, send))

    assert captured.get("status") == 403
    assert "called" not in captured
    import json

    body = json.loads(captured["body"])
    assert body["success"] is False
    assert body["error"]["code"] == "FORBIDDEN"


# ---------------------------------------------------------------- 幂等


def _create_payload(name: str) -> dict:
    return {"name": name}


def test_idempotent_replay_returns_original_response(seeded):
    """同 key 同 body 第二次提交：返回原响应、不重复创建。"""
    cats = seeded.get("/api/v1/categories").json()["data"]["items"]
    key = f"test-{uuid.uuid4()}"

    first = seeded.post(
        "/api/v1/categories", json=_create_payload("幂等测试A"), headers={"Idempotency-Key": key}
    )
    assert first.status_code == 201, first.text

    second = seeded.post(
        "/api/v1/categories", json=_create_payload("幂等测试A"), headers={"Idempotency-Key": key}
    )
    assert second.status_code == 201
    assert second.json()["data"]["id"] == first.json()["data"]["id"]
    assert second.headers.get("idempotency-replayed") == "1"

    # 只应存在一个同名分类
    names = [c["name"] for c in seeded.get("/api/v1/categories").json()["data"]["items"]]
    assert names.count("幂等测试A") == 1
    assert cats is not None


def test_idempotency_key_conflict_on_different_body(seeded):
    """同 key 不同 body：409 DUPLICATE_REQUEST。"""
    key = f"test-{uuid.uuid4()}"
    assert seeded.post(
        "/api/v1/categories", json=_create_payload("幂等测试B"), headers={"Idempotency-Key": key}
    ).status_code == 201

    conflict = seeded.post(
        "/api/v1/categories", json=_create_payload("幂等测试C"), headers={"Idempotency-Key": key}
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "DUPLICATE_REQUEST"

    names = [c["name"] for c in seeded.get("/api/v1/categories").json()["data"]["items"]]
    assert "幂等测试C" not in names


def test_no_key_means_no_idempotency(seeded):
    """不带 Idempotency-Key 时不做去重（允许手工调试重复提交）。"""
    key_payload = _create_payload("幂等测试D")
    assert seeded.post("/api/v1/categories", json=key_payload).status_code == 201
    # 第二次同名 → 唯一约束冲突 409，说明确实执行了而不是被缓存拦截
    second = seeded.post("/api/v1/categories", json=key_payload)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "CONFLICT"


def test_failed_response_not_cached(seeded):
    """失败响应不缓存：修正参数后同 key 重试应成功。"""
    key = f"test-{uuid.uuid4()}"
    bad = seeded.post("/api/v1/categories", json={"name": ""}, headers={"Idempotency-Key": key})
    assert bad.status_code == 400

    good = seeded.post(
        "/api/v1/categories", json=_create_payload("幂等测试E"), headers={"Idempotency-Key": key}
    )
    assert good.status_code == 201


def test_get_requests_bypass_idempotency(client, clean_db):
    """GET 即使带 key 也不走幂等逻辑，且不应报错。"""
    res = client.get("/api/v1/ping", headers={"Idempotency-Key": "whatever"})
    assert res.status_code == 200
    assert "idempotency-replayed" not in res.headers
