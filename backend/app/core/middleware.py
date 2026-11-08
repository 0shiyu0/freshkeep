"""网络边界与幂等两个中间件。

均为**原生 ASGI 中间件**，不用 BaseHTTPMiddleware：
后者的 call_next 与请求体读取会互相干扰（读了 body 下游会挂），而幂等需要读 body 做哈希。

CIDR（docs/ARCHITECTURE.md §9）：只放行 ALLOW_CIDR 里的网段，其余返回 403。
幂等（API 契约 §1.4）：POST/PUT/PATCH/DELETE 带 Idempotency-Key 时，
同 key 同 body 返回原响应；同 key 不同 body 返回 409 DUPLICATE_REQUEST。
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60      # 保留 24 小时
MAX_CACHE_BYTES = 256 * 1024                # 超过 256KB 的响应不缓存
_SKIP_PATHS = {"/health", "/api/v1/health", "/api/v1/ping"}


# ---------------------------------------------------------------- 工具


async def _send_json(send, status: int, payload: dict, extra_headers=None):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(body)).encode()),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def _header(scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return None


def client_ip(scope) -> str | None:
    """取真实客户端 IP。TRUST_PROXY=1 时优先 X-Forwarded-For 的第一段。"""
    if settings.trust_proxy:
        forwarded = _header(scope, b"x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else None


# ---------------------------------------------------------------- CIDR


class CidrMiddleware:
    """网段白名单。

    无法解析成 IP 的客户端（测试客户端的 `testclient`、Unix socket）视为本地直连放行，
    本机回环也放行——这样 `pytest`、容器健康检查与本地调试都不需要额外配置，
    而来自真实网段的请求仍严格校验。
    """

    def __init__(self, app):
        self.app = app
        self._networks = settings.allow_networks()

    def _allowed(self, ip: str | None) -> bool:
        if not ip:
            return True
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return True
        if addr.is_loopback:
            return True
        if not self._networks:
            return True
        return any(addr in net for net in self._networks)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        ip = client_ip(scope)
        if self._allowed(ip):
            await self.app(scope, receive, send)
            return

        log.warning("拒绝非白名单网段访问：ip=%s path=%s", ip, scope.get("path"))
        await _send_json(
            send,
            403,
            {
                "success": False,
                "error": {
                    "code": "FORBIDDEN",
                    "message": f"来源地址 {ip} 不在允许的网段内（见 ALLOW_CIDR）",
                },
                "request_id": "",
            },
        )


# ---------------------------------------------------------------- 幂等


class IdempotencyMiddleware:
    """写操作幂等。

    取舍：
    - 只对带 `Idempotency-Key` 头的写请求生效，不带的照常执行（便于手工调试）
    - 只缓存 JSON 响应且状态码 < 400；失败响应不缓存，允许客户端修正后重试
    - 响应边转发边收集，转发行为与不装中间件时一致；流式响应不缓存
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in WRITE_METHODS:
            await self.app(scope, receive, send)
            return

        key = _header(scope, b"idempotency-key")
        path = scope.get("path", "")
        if not key or path in _SKIP_PATHS or path.startswith("/docs"):
            await self.app(scope, receive, send)
            return

        # 读完整请求体（哈希需要），随后用回放函数交给下游
        body = b""
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break

        request_hash = hashlib.sha256(body).hexdigest()

        from app.db.session import SessionLocal
        from app.models import IdempotencyKey

        cached: tuple[int, dict] | None = None
        try:
            with SessionLocal() as db:
                row = db.get(IdempotencyKey, key)
                if row is not None:
                    if row.request_hash != request_hash:
                        await _send_json(
                            send,
                            409,
                            {
                                "success": False,
                                "error": {
                                    "code": "DUPLICATE_REQUEST",
                                    "message": "该 Idempotency-Key 已用于另一个不同请求",
                                },
                                "request_id": "",
                            },
                        )
                        return
                    cached = (row.status_code, row.response_json)
                _purge_expired(db)
        except Exception as exc:  # noqa: BLE001 - 幂等表不可用不应阻断业务
            log.warning("幂等表不可用，本次跳过：%s", exc)

        if cached is not None:
            status, payload = cached
            log.info("幂等命中，返回原响应 key=%s", key)
            await _send_json(send, status, payload, extra_headers=[(b"idempotency-replayed", b"1")])
            return

        async def replay_receive():
            return {"type": "http.request", "body": body, "more_body": False}

        started: dict = {}
        chunks: list[bytes] = []
        too_large = False

        async def send_capture(message):
            nonlocal too_large
            if message["type"] == "http.response.start":
                started.update(message)
            elif message["type"] == "http.response.body":
                if not too_large:
                    chunks.append(message.get("body", b""))
                    if sum(len(c) for c in chunks) > MAX_CACHE_BYTES:
                        too_large = True
                        chunks.clear()
            await send(message)      # 始终转发，不改变响应行为

        await self.app(scope, replay_receive, send_capture)

        if too_large or not chunks:
            return

        status = started.get("status", 500)
        headers = {k.lower(): v for k, v in started.get("headers", [])}
        content_type = headers.get(b"content-type", b"").decode("latin-1")
        if status >= 400 or not content_type.startswith("application/json"):
            return

        raw = b"".join(chunks)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return

        try:
            with SessionLocal() as db:
                if db.get(IdempotencyKey, key) is None:
                    db.add(
                        IdempotencyKey(
                            key=key,
                            request_hash=request_hash,
                            status_code=status,
                            response_json=payload,
                        )
                    )
                    db.commit()
        except Exception as exc:  # noqa: BLE001 - 写缓存失败不影响本次响应
            log.warning("幂等结果落库失败 key=%s：%s", key, exc)


def _purge_expired(db) -> None:
    """顺手清理过期记录，避免幂等表无限增长。"""
    from app.models import IdempotencyKey

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=IDEMPOTENCY_TTL_SECONDS)
    db.execute(delete(IdempotencyKey).where(IdempotencyKey.created_at < cutoff))
    db.commit()
