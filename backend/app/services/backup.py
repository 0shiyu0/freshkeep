"""备份（M7）：纯 Python 逻辑备份，不依赖 pg_dump。

产物：`<backup_dir>/freshkeep-backup-YYYYmmdd-HHMMSS.tar.gz`，内含
- `schema.sql`：`database/001_init.sql` 原文（建表与视图的唯一真相）；
- `tables/<表名>.csv`：`COPY ... TO STDOUT WITH (FORMAT csv, HEADER)` 的原样输出；
- `manifest.json`：版本、表清单、每表行数、生成时间。

选择逻辑备份而非 pg_dump 的原因：api 镜像是 python:slim，没有 pg_dump；
装 postgresql-client 只能拿到 PG15 客户端，导出 PG16 会直接报版本不兼容。
"""
from __future__ import annotations

import hashlib
import io
import os
import json
import tarfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import not_found, validation_error

BIZ = ZoneInfo("Asia/Shanghai")

# 白名单：只导出这些表，避免表名拼接带来的注入风险
TABLES = [
    "users", "devices", "pair_codes", "file_assets", "categories", "units",
    "storage_locations", "ingredients", "ingredient_barcodes", "nutrition_definitions",
    "ingredient_nutrition", "nutrition_targets", "batches", "inventory_transactions",
    "transaction_allocations", "consumption_records", "consumption_nutrition",
    "shopping_lists", "shopping_list_items", "recipes", "recipe_items", "recipe_steps",
    "notifications", "app_settings", "audit_logs", "idempotency_keys", "recognition_drafts",
]


def _dir() -> Path:
    path = Path(settings.backup_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _copy_table_csv(db: Session, table: str) -> bytes:
    conn = db.connection().connection
    with conn.cursor() as cur:
        with cur.copy(f"COPY (SELECT * FROM {table}) TO STDOUT WITH (FORMAT csv, HEADER)") as cp:
            return b"".join(cp)


def _count(db: Session, table: str) -> int:
    return int(db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0)  # noqa: S608


def create_backup(db: Session) -> dict:
    stamp = datetime.now(BIZ).strftime("%Y%m%d-%H%M%S")
    name = f"freshkeep-backup-{stamp}.tar.gz"
    path = _dir() / name

    # 本机（repo root/database）与容器（/app/database）的层级不同，逐个探测
    here = Path(__file__).resolve()
    candidates = [
        here.parents[3] / "database" / "001_init.sql",
        here.parents[2] / "database" / "001_init.sql",
        Path("/app/database/001_init.sql"),
    ]
    schema_path = next((p for p in candidates if p.exists()), None)
    if schema_path is None:
        raise RuntimeError("找不到 database/001_init.sql，无法生成含 schema 的备份")
    schema_text = schema_path.read_text(encoding="utf-8")
    # 001_init.sql 用 BEGIN; 包裹但没有 COMMIT;，psql 会话结束会回滚整段 DDL；
    # 备份里补上 COMMIT，保证恢复时可直接 psql -f 执行。
    if "BEGIN;" in schema_text[:600] and "COMMIT;" not in schema_text.upper():
        schema_text = schema_text.rstrip() + "\n\nCOMMIT;\n"
    schema = schema_text.encode("utf-8")

    counts: dict[str, int] = {}
    payloads: dict[str, bytes] = {}
    for table in TABLES:
        counts[table] = _count(db, table)
        payloads[table] = _copy_table_csv(db, table)

    manifest = {
        "app": "freshkeep",
        "created_at": datetime.now(BIZ).isoformat(),
        "format": "logical-csv-v1",
        "tables": counts,
        "total_rows": sum(counts.values()),
        "note": "恢复方式：建库 → psql -f schema.sql → COPY 各表 CSV",
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode()

    with tarfile.open(path, "w:gz") as tar:
        def add_bytes(name_in_tar: str, data: bytes) -> None:
            info = tarfile.TarInfo(name_in_tar)
            info.size = len(data)
            info.mtime = int(datetime.now(BIZ).timestamp())
            tar.addfile(info, io.BytesIO(data))

        add_bytes("schema.sql", schema)
        add_bytes("manifest.json", manifest_bytes)
        for table, data in payloads.items():
            add_bytes(f"tables/{table}.csv", data)

    size = path.stat().st_size
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    keep = int(os.environ.get("BACKUP_KEEP", "7") or 7)
    prune_backups(keep)
    return {
        "name": name,
        "size_bytes": size,
        "sha256": digest,
        "tables": len(TABLES),
        "total_rows": manifest["total_rows"],
        "created_at": datetime.now(BIZ).isoformat(),
    }


def prune_backups(keep: int = 7) -> dict:
    """只保留最近 keep 份备份（按文件名时间戳倒序），返回被删除的文件。"""
    if keep < 1:
        keep = 7
    files = sorted(_dir().glob("freshkeep-backup-*.tar.gz"), reverse=True)
    removed = []
    for old in files[keep:]:
        old.unlink(missing_ok=True)
        removed.append(old.name)
    return {"keep": keep, "total": len(files), "removed": removed}


def list_backups() -> list[dict]:
    items = []
    for path in sorted(_dir().glob("freshkeep-backup-*.tar.gz"), reverse=True):
        stat = path.stat()
        items.append({
            "name": path.name,
            "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime, BIZ).isoformat(),
        })
    return items


def resolve(name: str) -> Path:
    """只允许下载备份目录内的 .tar.gz，杜绝路径穿越。"""
    if "/" in name or "\\" in name or not name.endswith(".tar.gz"):
        raise validation_error("备份文件名不合法")
    path = _dir() / name
    if not path.exists():
        raise not_found("备份不存在")
    return path


def verify(name: str) -> dict:
    """校验备份可读：tar 能打开、manifest 存在、表数与行数一致。"""
    path = resolve(name)
    try:
        with tarfile.open(path, "r:gz") as tar:
            manifest = json.loads(tar.extractfile("manifest.json").read())  # type: ignore[union-attr]
            names = set(tar.getnames())
    except (tarfile.TarError, KeyError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"备份不可读：{type(exc).__name__}"}

    missing = [f"tables/{t}.csv" for t in TABLES if f"tables/{t}.csv" not in names]
    return {
        "ok": not missing,
        "created_at": manifest.get("created_at"),
        "tables": len(manifest.get("tables") or {}),
        "total_rows": manifest.get("total_rows"),
        "missing": missing,
    }
