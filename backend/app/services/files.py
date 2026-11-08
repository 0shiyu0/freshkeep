"""图片与文件存取。

安全（docs/ARCHITECTURE.md §9）：
- 只接受 jpg/png/webp，按**魔数**校验而不只信 Content-Type
- 大小上限 5 MB，文件名由服务端生成（杜绝路径穿越）
- 按 sha256 去重：同一张图重复上传只落一份物理文件
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ApiError
from app.models import FileAsset

MAX_BYTES = 5 * 1024 * 1024

# mime -> (后缀, 魔数前缀判定函数)
_SIGNATURES: dict[str, tuple[str, callable]] = {
    "image/jpeg": (".jpg", lambda b: b[:3] == b"\xff\xd8\xff"),
    "image/png": (".png", lambda b: b[:8] == b"\x89PNG\r\n\x1a\n"),
    "image/webp": (".webp", lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP"),
}


def _sniff(data: bytes) -> str:
    for mime, (_, check) in _SIGNATURES.items():
        try:
            if check(data):
                return mime
        except IndexError:
            continue
    raise ApiError("UNSUPPORTED_MEDIA", "只支持 JPG / PNG / WebP 图片", 415)


def upload_dir() -> Path:
    return Path(settings.storage_dir) / "uploads"


def save_image(db: Session, data: bytes, declared_mime: str | None = None) -> FileAsset:
    if not data:
        raise ApiError("EMPTY_FILE", "文件为空", 400)
    if len(data) > MAX_BYTES:
        raise ApiError("FILE_TOO_LARGE", "图片不能超过 5 MB", 413)

    mime = _sniff(data)
    if declared_mime and declared_mime not in _SIGNATURES:
        raise ApiError("UNSUPPORTED_MEDIA", "只支持 JPG / PNG / WebP 图片", 415)

    checksum = hashlib.sha256(data).hexdigest()
    existing = db.execute(select(FileAsset).where(FileAsset.checksum == checksum)).scalar_one_or_none()
    if existing is not None:
        return existing   # 同一张图复用，不重复落盘

    suffix = _SIGNATURES[mime][0]
    now = datetime.now()
    rel = Path("uploads") / f"{now:%Y%m}" / f"{uuid.uuid4().hex}{suffix}"
    abs_path = Path(settings.storage_dir) / rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(data)

    asset = FileAsset(
        storage_path=str(rel),
        mime_type=mime,
        size_bytes=len(data),
        checksum=checksum,
        category="image",
    )
    db.add(asset)
    db.flush()
    return asset


def absolute_path(asset: FileAsset) -> Path:
    return Path(settings.storage_dir) / asset.storage_path


def delete_asset(db: Session, asset: FileAsset) -> None:
    path = absolute_path(asset)
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:  # 文件删不掉不应阻断记录清理
        raise ApiError("FILE_DELETE_FAILED", f"删除文件失败：{exc}", 500) from exc
    db.delete(asset)
