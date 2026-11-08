"""命令行工具。

用法：
  python -m app.cli pair            生成一次性配对码（10 分钟有效）
  python -m app.cli devices         列出已授权设备
  python -m app.cli revoke <id>     吊销设备
"""
from __future__ import annotations

import argparse
import hashlib
import secrets
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.core.config import settings
from app.db.session import SessionLocal

# 去掉 0/O/1/I/L 等易混字符，手抄不会错
ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def gen_code(length: int = 6) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ensure_schema(db) -> bool:
    try:
        db.execute(text("SELECT 1 FROM pair_codes LIMIT 1"))
        return True
    except Exception:  # noqa: BLE001 - 表不存在即未迁移
        print("数据库尚未初始化，请先执行：alembic upgrade head", file=sys.stderr)
        return False


def cmd_pair(_: argparse.Namespace) -> int:
    code = gen_code()
    with SessionLocal() as db:
        if not _ensure_schema(db):
            return 1
        db.execute(
            text("INSERT INTO pair_codes (code_hash, expires_at) VALUES (:h, :e)"),
            {
                "h": sha256(code),
                "e": datetime.now(timezone.utc)
                + timedelta(minutes=settings.pair_code_ttl_minutes),
            },
        )
        db.commit()
    print(f"配对码 {code}（{settings.pair_code_ttl_minutes} 分钟内有效，一次性）")
    print("网页：打开 http://<NAS_IP>:8080 输入该码；App：填地址后在配对页输入该码")
    return 0


def cmd_devices(_: argparse.Namespace) -> int:
    with SessionLocal() as db:
        if not _ensure_schema(db):
            return 1
        rows = db.execute(
            text(
                "SELECT id, name, platform, last_seen_at, revoked_at "
                "FROM devices ORDER BY created_at DESC"
            )
        ).all()
    if not rows:
        print("还没有已授权设备。执行 `python -m app.cli pair` 生成配对码。")
        return 0
    for r in rows:
        state = "已吊销" if r.revoked_at else "有效"
        print(f"{r.id}  {r.platform:<7} {r.name:<20} 最后活跃 {r.last_seen_at or '-'}  {state}")
    return 0


def cmd_revoke(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        if not _ensure_schema(db):
            return 1
        res = db.execute(
            text("UPDATE devices SET revoked_at = now() WHERE id = :id AND revoked_at IS NULL"),
            {"id": args.device_id},
        )
        db.commit()
    if res.rowcount == 0:
        print("未找到该设备，或已处于吊销状态", file=sys.stderr)
        return 1
    print(f"已吊销设备 {args.device_id}，该令牌立即失效")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description="鲜度 FreshKeep 命令行")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("pair", help="生成一次性配对码").set_defaults(func=cmd_pair)
    sub.add_parser("devices", help="列出已授权设备").set_defaults(func=cmd_devices)

    p_revoke = sub.add_parser("revoke", help="吊销设备")
    p_revoke.add_argument("device_id")
    p_revoke.set_defaults(func=cmd_revoke)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
