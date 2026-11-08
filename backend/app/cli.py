"""命令行工具。

用法：
  python -m app.cli seed            写入基础字典（单位/分类/位置/营养项目），幂等
  python -m app.cli pair            生成一次性配对码（10 分钟有效）
  python -m app.cli devices         列出已授权设备
  python -m app.cli revoke <id>     吊销设备
  python -m app.cli set-password    交互式设置登录密码
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import secrets
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text

from app.core.config import settings
from app.db.session import SessionLocal

# 去掉 0/O/1/I/L 等易混字符，手抄不会错
ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"

# ---------------------------------------------------------------- 基础字典

UNITS = [
    # (名称, 符号, 维度, 小数位, 是否系统内置)
    ("克", "g", "weight", 1, True),
    ("千克", "kg", "weight", 3, True),
    ("毫升", "ml", "volume", 1, True),
    ("升", "L", "volume", 3, True),
    ("个", "个", "quantity", 0, True),
    ("包", "包", "quantity", 0, True),
    ("瓶", "瓶", "quantity", 0, True),
    ("盒", "盒", "quantity", 0, True),
    ("袋", "袋", "quantity", 0, True),
]

# (父级名, 子级名列表)；父级为空表示顶层
CATEGORIES = [
    ("蔬菜", ["叶菜", "根茎", "菌菇"]),
    ("肉类", ["常见食材", "禽类", "畜类"]),
    ("水产", ["鱼类", "虾蟹", "贝类"]),
    ("蛋奶", []),
    ("主食", []),
    ("调料", []),
    ("水果", []),
    ("其他", []),
]

LOCATIONS = [
    ("冷冻室", "冷冻层，-18℃"),
    ("冷藏室", "保鲜层，0~4℃"),
    ("常温", "橱柜外，避光"),
    ("橱柜", "干货收纳"),
]

NUTRITION = [
    # (code, 名称, 单位, 排序)
    ("calories", "热量", "kcal", 1),
    ("protein", "蛋白质", "g", 2),
    ("fat", "脂肪", "g", 3),
    ("carbs", "碳水化合物", "g", 4),
    ("fiber", "膳食纤维", "g", 5),
    ("sodium", "钠", "mg", 6),
]


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


# ---------------------------------------------------------------- seed


def cmd_seed(args: argparse.Namespace) -> int:
    """写入基础字典。已存在的项跳过（按名称/编码判重），可重复执行。"""
    from app.models import Category, NutritionDefinition, StorageLocation, Unit

    with SessionLocal() as db:
        if not _ensure_schema(db):
            return 1

        created = {"units": 0, "categories": 0, "locations": 0, "nutrition": 0}

        # 单位
        existing_units = {u.name for u in db.execute(select(Unit)).scalars()}
        for name, symbol, dim, prec, system in UNITS:
            if name in existing_units:
                continue
            db.add(Unit(name=name, symbol=symbol, dimension=dim, precision=prec, is_system=system))
            created["units"] += 1

        # 营养项目
        existing_nut = {n.code for n in db.execute(select(NutritionDefinition)).scalars()}
        for code, name, unit, order in NUTRITION:
            if code in existing_nut:
                continue
            db.add(NutritionDefinition(code=code, name=name, unit=unit, sort_order=order))
            created["nutrition"] += 1

        # 储存位置
        existing_locs = {l.name for l in db.execute(select(StorageLocation)).scalars()}
        for idx, (name, desc) in enumerate(LOCATIONS):
            if name in existing_locs:
                continue
            db.add(StorageLocation(name=name, description=desc, sort_order=idx))
            created["locations"] += 1

        # 分类（两级）
        db.flush()
        cats = {c.name: c for c in db.execute(select(Category)).scalars()}
        for order, (name, children) in enumerate(CATEGORIES):
            parent = cats.get(name)
            if parent is None:
                parent = Category(name=name, parent_id=None, sort_order=order)
                db.add(parent)
                db.flush()
                cats[name] = parent
                created["categories"] += 1
            for c_order, child in enumerate(children):
                if child in cats:
                    continue
                node = Category(name=child, parent_id=parent.id, sort_order=c_order)
                db.add(node)
                db.flush()
                cats[child] = node
                created["categories"] += 1

        db.commit()

    if args.if_empty and sum(created.values()) == 0:
        return 0
    print(
        "基础字典已就绪："
        f"新增单位 {created['units']}、分类 {created['categories']}、"
        f"位置 {created['locations']}、营养项目 {created['nutrition']}"
    )
    return 0


# ---------------------------------------------------------------- 认证相关


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


def cmd_set_password(args: argparse.Namespace) -> int:
    """设置/重置登录密码（在服务器上执行，等价于"有物理访问权"）。"""
    from app.models import User
    from app.services.auth import get_owner, hash_password

    pwd = args.password or getpass.getpass("新密码（不少于 8 位）：")
    if len(pwd) < 8:
        print("密码至少 8 位", file=sys.stderr)
        return 1
    if not args.password:
        again = getpass.getpass("再输一次：")
        if again != pwd:
            print("两次输入不一致", file=sys.stderr)
            return 1

    with SessionLocal() as db:
        if not _ensure_schema(db):
            return 1
        user = get_owner(db)
        user.password_hash = hash_password(pwd)
        db.commit()
        print(f"已为 {user.username} 设置密码，可用用户名 + 密码登录")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description="鲜度 FreshKeep 命令行")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_seed = sub.add_parser("seed", help="写入基础字典（单位/分类/位置/营养项目）")
    p_seed.add_argument("--if-empty", action="store_true", help="无新增时不输出")
    p_seed.set_defaults(func=cmd_seed)

    sub.add_parser("pair", help="生成一次性配对码").set_defaults(func=cmd_pair)
    sub.add_parser("devices", help="列出已授权设备").set_defaults(func=cmd_devices)

    p_revoke = sub.add_parser("revoke", help="吊销设备")
    p_revoke.add_argument("device_id")
    p_revoke.set_defaults(func=cmd_revoke)

    p_pwd = sub.add_parser("set-password", help="设置登录密码")
    p_pwd.add_argument("--password", help="直接传入密码（不推荐，会留在 shell 历史里）")
    p_pwd.set_defaults(func=cmd_set_password)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
