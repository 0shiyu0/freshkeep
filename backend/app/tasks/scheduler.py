"""APScheduler 定时任务（M7）。

三个作业（Asia/Shanghai）：
- 03:00 `daily_reconcile`：按流水修正批次缓存并写审计；
- 03:10 `daily_backup`：生成逻辑备份；
- 08:00 `expiring_scan`：扫描临期/过期/低库存生成通知。

开关：`ENABLE_SCHEDULER=true` 才启动（测试与本地默认关闭，避免污染数据）。
每个作业都写 `audit_logs`，失败也不抛出到主进程。
"""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import text

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal

log = get_logger("app.tasks")
BIZ = ZoneInfo("Asia/Shanghai")
_scheduler: BackgroundScheduler | None = None

JOBS = {
    "daily_reconcile": {"hour": 3, "minute": 0, "desc": "每日对账（按流水修正缓存）"},
    "daily_backup": {"hour": 3, "minute": 10, "desc": "每日逻辑备份"},
    "expiring_scan": {"hour": 8, "minute": 0, "desc": "临期/过期/低库存扫描"},
}


def _audit(db, action: str, payload: dict) -> None:
    db.execute(
        text(
            "INSERT INTO audit_logs (action, object_type, after_json) "
            "VALUES (:a, 'system', CAST(:p AS jsonb))"
        ),
        {"a": action, "p": json.dumps(payload, ensure_ascii=False, default=str)},
    )


def job_reconcile() -> dict:
    """与 `POST /inventory/reconcile/repair` 同口径：按分配聚合覆盖缓存。"""
    with SessionLocal() as db:
        rows = db.execute(
            text(
                "SELECT batch_id, allocated_quantity, allocated_weight, allocated_cost "
                "FROM v_batch_reconcile "
                "WHERE diff_quantity <> 0 OR diff_weight <> 0 OR diff_cost <> 0"
            )
        ).all()
        for r in rows:
            db.execute(
                text(
                    "UPDATE batches SET remaining_quantity=CAST(:q AS numeric), "
                    "remaining_weight=CAST(:w AS numeric), remaining_cost=CAST(:c AS numeric) "
                    "WHERE id = CAST(:b AS uuid)"
                ),
                {"q": str(r.allocated_quantity), "w": str(r.allocated_weight),
                 "c": str(r.allocated_cost), "b": str(r.batch_id)},
            )
        _audit(db, "scheduler_reconcile", {"repaired": len(rows), "at": datetime.now(BIZ).isoformat()})
        db.commit()
    log.info("对账作业完成，修复 %s 个批次", len(rows))
    return {"repaired": len(rows)}


def job_backup() -> dict:
    from app.services.backup import create_backup

    with SessionLocal() as db:
        info = create_backup(db)
        _audit(db, "scheduler_backup", info)
        db.commit()
    log.info("备份作业完成：%s", info["name"])
    return info


def job_scan() -> dict:
    from app.services.alerts import scan

    with SessionLocal() as db:
        info = scan(db, days=7)
        _audit(db, "scheduler_scan", info)
        db.commit()
    log.info("临期扫描完成：新增 %s 条", info["created"])
    return info


_RUNNERS = {
    "daily_reconcile": job_reconcile,
    "daily_backup": job_backup,
    "expiring_scan": job_scan,
}


def start_scheduler() -> bool:
    global _scheduler
    if _scheduler is not None:
        return True
    if not settings.enable_scheduler:
        log.info("定时任务未启用（ENABLE_SCHEDULER=false）")
        return False
    _scheduler = BackgroundScheduler(timezone=str(BIZ))
    for job_id, cfg in JOBS.items():
        _scheduler.add_job(
            _RUNNERS[job_id],
            CronTrigger(hour=cfg["hour"], minute=cfg["minute"], timezone=str(BIZ)),
            id=job_id, replace_existing=True, max_instances=1, coalesce=True,
        )
    _scheduler.start()
    log.info("定时任务已启动：%s", ", ".join(JOBS))
    return True


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def status() -> dict:
    return {
        "enabled": settings.enable_scheduler,
        "running": _scheduler is not None,
        "jobs": [
            {
                "id": job_id, "desc": cfg["desc"],
                "cron": f"{cfg['hour']:02d}:{cfg['minute']:02d}",
                "next_run": (
                    str(_scheduler.get_job(job_id).next_run_time)
                    if _scheduler and _scheduler.get_job(job_id) else None
                ),
            }
            for job_id, cfg in JOBS.items()
        ],
    }


def run_now(job_id: str) -> dict:
    runner = _RUNNERS.get(job_id)
    if runner is None:
        raise ValueError(f"未知作业：{job_id}")
    return runner()
