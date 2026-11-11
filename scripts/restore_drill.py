#!/usr/bin/env python3
"""阶段 9 · 恢复演练：把逻辑备份恢复到**临时库**并逐表核对，不触碰生产库。

用法：
  python3 scripts/restore_drill.py                        # 用 backups/ 里最新一份
  python3 scripts/restore_drill.py --backup <path> --report <json path>
  python3 scripts/restore_drill.py --psql-cmd "docker compose exec -T db"  # 在 NAS 容器内演练

演练库名 freshkeep_drill_<时间戳>，结束后必定 DROP。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PSQL = "/opt/homebrew/opt/postgresql@16/bin/psql"
DB_USER = os.environ.get("PGUSER", "shiyu")
drill_user = DB_USER
DB_HOST = os.environ.get("PGHOST", "127.0.0.1")
DB_PORT = os.environ.get("PGPORT", "5432")


def newest_backup() -> Path:
    files = sorted((ROOT / "backups").glob("freshkeep-backup-*.tar.gz"), reverse=True)
    if not files:
        raise SystemExit("没有找到备份，请先运行 POST /backup 或 POST /tasks/daily_backup/run")
    return files[0]


def run(args: list[str], *, quiet: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backup", default=None)
    ap.add_argument("--psql", default=DEFAULT_PSQL)
    ap.add_argument("--psql-cmd", default=None,
                    help='额外前缀，例如 "docker compose exec -T db"；此时 --psql 是容器内路径')
    ap.add_argument("--report", default=None)
    ap.add_argument("--keep-drill-db", action="store_true", help="调试用：不删除演练库")
    args = ap.parse_args()

    backup = Path(args.backup) if args.backup else newest_backup()
    if not backup.exists():
        raise SystemExit(f"备份不存在：{backup}")

    admin_db = "postgres"
    if args.psql_cmd:
        admin_db = os.environ.get("DRILL_ADMIN_DB", "freshkeep")

    def _container() -> str | None:
        m = re.match(r"docker\s+exec\s+(?:-\S+\s+)*(\S+)", args.psql_cmd or "")
        return m.group(1) if m else None

    def _push(path: Path) -> str:
        """docker exec 模式下把宿主机文件复制进容器，返回容器内路径。"""
        container = _container()
        if not container:
            return str(path)
        dest = f"/tmp/drill-{path.name}"
        run(["docker", "cp", str(path), f"{container}:{dest}"])
        return dest

    if args.psql_cmd and "{db}" in args.psql_cmd:
        # 例如 NAS：--psql-cmd "docker exec freshkeep-db psql -U freshkeep -d {db}"
        def psql(db: str, sql: str, *, file: Path | None = None):
            cmd = args.psql_cmd.format(db=db).split()
            cmd += ["-tA", "-v", "ON_ERROR_STOP=1"] + (["-f", _push(file)] if file else ["-c", sql])
            r = run(cmd)
            return r.returncode, r.stdout, r.stderr
    elif args.psql_cmd:
        def psql(db: str, sql: str, *, file: Path | None = None):
            cmd = args.psql_cmd.split() + [args.psql, "-U", drill_user, "-d", db,
                                           "-tA", "-v", "ON_ERROR_STOP=1"]
            cmd += (["-f", str(file)] if file else ["-c", sql])
            r = run(cmd)
            return r.returncode, r.stdout, r.stderr
    else:
        def psql(db: str, sql: str, *, file: Path | None = None):
            cmd = [args.psql, "-U", drill_user, "-d", db, "-tA", "-v", "ON_ERROR_STOP=1"]
            cmd += (["-f", str(file)] if file else ["-c", sql])
            r = run(cmd)
            return r.returncode, r.stdout, r.stderr

    drill = f"freshkeep_drill_{int(time.time())}"
    report: dict = {
        "backup": backup.name,
        "backup_size_bytes": backup.stat().st_size,
        "drill_database": drill,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "steps": [],
        "ok": False,
    }

    tmp = Path(tempfile.mkdtemp(prefix="fk-drill-"))
    try:
        # 1) 解包
        with tarfile.open(backup, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name.startswith("/") or ".." in member.name:
                    raise SystemExit(f"备份内含不安全路径：{member.name}")
            tar.extractall(tmp)
        manifest = json.loads((tmp / "manifest.json").read_text(encoding="utf-8"))
        report["manifest_tables"] = len(manifest["tables"])
        report["manifest_rows"] = manifest["total_rows"]
        report["steps"].append({"step": "extract", "ok": True, "files": len(list(tmp.rglob("*.csv")))})

        # 2) 建临时库
        rc, out, err = psql(admin_db, f'DROP DATABASE IF EXISTS "{drill}"')
        rc2, out2, err2 = psql(admin_db, f'CREATE DATABASE "{drill}"')
        if rc2 != 0:
            raise RuntimeError(f"创建演练库失败：{err2.strip()[:300]}")
        report["steps"].append({"step": "create_database", "ok": True})

        # 3) 恢复 schema（旧备份若缺 COMMIT 就补上，避免会话结束回滚）
        schema_file = tmp / "schema.sql"
        schema_text = schema_file.read_text(encoding="utf-8")
        if "schema.sql 缺失" in schema_text:
            raise RuntimeError("该备份不含 schema.sql，请用修复后的版本重新生成备份")
        if "BEGIN;" in schema_text[:600] and "COMMIT;" not in schema_text.upper():
            schema_file.write_text(schema_text.rstrip() + "\n\nCOMMIT;\n", encoding="utf-8")
        rc, out, err = psql(drill, "", file=schema_file)
        if rc != 0:
            raise RuntimeError(f"schema 恢复失败：{err.strip()[:400]}")
        rc_check, out_check, _ = psql(drill, "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")
        table_count = int((out_check or "0").strip().splitlines()[-1]) if rc_check == 0 else 0
        if table_count < 20:
            raise RuntimeError(f"schema 未生效（只建出 {table_count} 张表）")
        report["steps"].append({"step": "restore_schema", "ok": True, "base_tables": table_count})

        # 4) 逐表 COPY（顺序与备份一致）
        restored = {}
        errors = []
        for table, expected in manifest["tables"].items():
            csv = tmp / "tables" / f"{table}.csv"
            if not csv.exists():
                errors.append(f"{table}: CSV 缺失")
                continue
            rc, out, err = psql(drill, f"\\copy {table} FROM '{_push(csv)}' WITH (FORMAT csv, HEADER)")
            if rc != 0:
                errors.append(f"{table}: {err.strip()[:160]}")
                continue
            rc3, out3, _ = psql(drill, f"SELECT COUNT(*) FROM {table}")
            actual = int((out3 or "0").strip().splitlines()[-1]) if rc3 == 0 and out3.strip() else -1
            restored[table] = {"expected": expected, "actual": actual,
                               "match": actual == expected}
            if actual != expected:
                errors.append(f"{table}: 行数 {actual} != {expected}")
        report["steps"].append({"step": "restore_tables", "ok": not errors,
                               "tables": len(restored), "errors": errors[:10]})
        report["tables"] = restored

        # 5) 抽查关键表
        samples = {}
        for table in ("ingredients", "batches", "inventory_transactions"):
            rc, out, _ = psql(drill, f"SELECT COUNT(*) FROM {table}")
            samples[table] = (out or "").strip().splitlines()[-1] if rc == 0 else None
        report["samples"] = samples

        report["ok"] = not errors and len(restored) == len(manifest["tables"])
        report["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as exc:  # noqa: BLE001
        report["error"] = str(exc)
    finally:
        if not args.keep_drill_db:
            # 断开可能存在的连接后删除
            psql(admin_db, f'DROP DATABASE IF EXISTS "{drill}" WITH (FORCE)')
        shutil.rmtree(tmp, ignore_errors=True)

    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
