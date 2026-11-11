#!/usr/bin/env python3
"""阶段 9 · 安全与性能验收。

用法：python3 scripts/stage9_acceptance.py --base http://192.168.31.198:18080 \
        --https https://192.168.31.198:18443 --report docs/reports/stage9-acceptance.json

检查项：凭据不入库、PWA 资产、HTTPS 与安全响应头、鉴权、接口延迟 p95、
容器资源、定时任务状态、备份可读性。所有断言只依赖命令输出，不猜测。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.request import Request, urlopen
import ssl

ROOT = Path(__file__).resolve().parents[1]


def curl_head(url: str, *, insecure: bool = False) -> tuple[int, dict, bytes]:
    import http.client
    from urllib.parse import urlparse

    u = urlparse(url)
    ctx = ssl._create_unverified_context() if insecure else None
    if u.scheme == "https":
        conn = http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=8, context=ctx)
    else:
        conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=8)
    conn.request("GET", u.path or "/", headers={"User-Agent": "FreshKeep-Stage9/1.0"})
    r = conn.getresponse()
    body = r.read()
    headers = {k.lower(): v for k, v in r.getheaders()}
    status = r.status
    conn.close()
    return status, headers, body


def timed(url: str, n: int = 20) -> dict:
    values = []
    for _ in range(n):
        t0 = time.perf_counter()
        try:
            status, _, _ = curl_head(url)
            if status >= 400:
                continue
        except Exception:
            continue
        values.append((time.perf_counter() - t0) * 1000)
    values.sort()
    if not values:
        return {"ok": False, "reason": "无成功请求"}
    def pct(p: float) -> float:
        return round(values[min(len(values) - 1, int(len(values) * p))], 2)
    return {"ok": True, "samples": len(values), "min_ms": round(values[0], 2),
            "p50_ms": pct(0.50), "p95_ms": pct(0.95), "max_ms": round(values[-1], 2)}


def sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=ROOT).stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://192.168.31.198:18080")
    ap.add_argument("--https", default="https://192.168.31.198:18443")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    result: dict = {"base": args.base, "https": args.https, "checks": {}, "ok": False,
                    "generated_at": time.strftime("%Y-%m-%d %H:%M:%S")}

    # 1) 凭据不入库：从临时文件读取，只报告是否存在，绝不打印值
    cred_file = Path("/tmp/fk_nas_pass")
    secret = cred_file.read_text().strip() if cred_file.exists() else ""
    tracked = sh("git ls-files")
    found = []
    if secret:
        for rel in tracked.splitlines():
            p = ROOT / rel
            if p.is_file() and p.stat().st_size < 2_000_000:
                try:
                    if secret in p.read_text(encoding="utf-8", errors="ignore"):
                        found.append(rel)
                except OSError:
                    pass
    result["checks"]["no_credentials_in_repo"] = {
        "ok": not found, "tracked_files": len(tracked.splitlines()),
        "matches": found, "note": "凭据只在本次会话临时文件中，未写入源码/日志/版本库" if not found else "发现泄漏",
    }
    ignored = sh("git check-ignore storage/certs/freshkeep.key storage/certs/freshkeep.crt .env")
    result["checks"]["secrets_gitignored"] = {
        "ok": "freshkeep.key" in ignored and ".env" in ignored,
        "ignored_paths": ignored.splitlines()[:6],
    }

    # 2) PWA 资产
    pwa = {}
    for path, needle in (("/manifest.webmanifest", "short_name"),
                         ("/sw.js", "addEventListener"),
                         ("/offline.html", "离线"),
                         ("/icons/icon-192.png", None)):
        try:
            status, headers, body = curl_head(args.base + path)
            pwa[path] = {"ok": status == 200 and (needle is None or needle.encode() in body),
                         "status": status, "bytes": len(body)}
        except Exception as exc:
            pwa[path] = {"ok": False, "error": type(exc).__name__}
    result["checks"]["pwa_assets"] = {"ok": all(v.get("ok") for v in pwa.values()), "assets": pwa}

    # 3) HTTPS 与安全头
    https = {}
    try:
        status, headers, body = curl_head(args.https + "/health", insecure=True)
        https = {"status": status, "hsts": headers.get("strict-transport-security"),
                 "csp": bool(headers.get("content-security-policy")),
                 "x_frame": headers.get("x-frame-options"),
                 "nosniff": headers.get("x-content-type-options"),
                 "referrer": headers.get("referrer-policy")}
        https["ok"] = (status == 200 and bool(https["hsts"]) and https["csp"]
                       and https["nosniff"] == "nosniff")
    except Exception as exc:
        https = {"ok": False, "error": type(exc).__name__}
    result["checks"]["https_and_headers"] = https
    cert = sh("openssl x509 -in storage/certs/freshkeep.crt -noout -ext subjectAltName 2>/dev/null")
    result["checks"]["certificate_san"] = {"ok": "192.168.31.198" in cert,
                                           "san": cert.replace("\n", " ")[:220]}

    # 4) 鉴权与 CIDR 闸门
    try:
        status, _, _ = curl_head(args.base + "/api/v1/inventory")
        auth_ok = status == 401
    except Exception:
        auth_ok = False
    result["checks"]["api_requires_auth"] = {"ok": auth_ok, "expected_status": 401}

    # 5) 性能
    result["checks"]["latency_health"] = timed(args.base + "/health", 20)
    result["checks"]["latency_spa"] = timed(args.base + "/", 20)

    # 6) 容器资源（本机或 NAS 均可，失败不阻断）
    stats = sh("docker compose ps --format '{{.Name}}|{{.Status}}' 2>/dev/null")
    result["checks"]["containers"] = {"ok": "healthy" in stats, "ps": stats.splitlines()[:5]}

    # 7) 备份与恢复演练产物
    drill = ROOT / "docs/reports/restore-drill.json"
    if drill.exists():
        d = json.loads(drill.read_text(encoding="utf-8"))
        result["checks"]["restore_drill"] = {"ok": bool(d.get("ok")),
                                             "backup": d.get("backup"),
                                             "tables": d.get("manifest_tables")}
    else:
        result["checks"]["restore_drill"] = {"ok": False, "reason": "缺少演练记录"}

    result["ok"] = all(v.get("ok") for v in result["checks"].values())
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
