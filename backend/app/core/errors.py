"""统一错误：所有业务异常走 ApiError，响应格式与 docs/api.md §1.2 一致。"""
from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """业务异常。status_code 决定 HTTP 状态，code 给客户端做分支。"""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            error["details"] = self.details
        return error


# 常用错误的便捷构造器（避免各处手写状态码，保证前后一致）
def validation_error(message: str = "参数不合法", **details: Any) -> ApiError:
    return ApiError("VALIDATION_ERROR", message, 400, details)


def unauthorized(message: str = "未认证或令牌已失效") -> ApiError:
    return ApiError("UNAUTHORIZED", message, 401)


def forbidden(message: str = "该网络不在允许范围内") -> ApiError:
    return ApiError("FORBIDDEN", message, 403)


def not_found(message: str = "资源不存在") -> ApiError:
    return ApiError("NOT_FOUND", message, 404)


def conflict(message: str = "状态冲突", code: str = "CONFLICT") -> ApiError:
    return ApiError(code, message, 409)


def insufficient_stock(required: str, available: str, shortage: str) -> ApiError:
    return ApiError(
        "INSUFFICIENT_STOCK",
        "可用量不足",
        422,
        {"required": required, "available": available, "shortage": shortage},
    )


def unit_not_convertible(message: str = "数量与重量之间没有换算关系") -> ApiError:
    return ApiError("UNIT_NOT_CONVERTIBLE", message, 422)


def inconsistent_measure(message: str = "数量与重量按换算关系不自洽") -> ApiError:
    return ApiError("INCONSISTENT_MEASURE", message, 422)
