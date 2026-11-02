import logging
import time

from fastapi import Header

from corp_assistant.config import get_settings
from corp_assistant.errors import AppError
from corp_assistant import store

logger = logging.getLogger(__name__)
_buckets: dict[str, list[float]] = {}


def reset_rate_limit() -> None:
    _buckets.clear()


def enforce_rate_limit(key: str) -> None:
    limit = get_settings().rate_limit_per_minute
    if limit <= 0:
        return
    now = time.monotonic()
    bucket = [stamp for stamp in _buckets.get(key, []) if now - stamp < 60]
    if len(bucket) >= limit:
        raise AppError(429, "请求过于频繁")
    bucket.append(now)
    _buckets[key] = bucket


def current_user(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> dict:
    settings = get_settings()
    if not x_api_key or x_api_key not in settings.api_keys:
        logger.warning("rejected api key")
        raise AppError(401, "API Key 无效")
    enforce_rate_limit(x_api_key)
    if not x_user_id:
        raise AppError(401, "缺少请求头 X-User-Id")
    user = store.get_employee(x_user_id)
    if user is None:
        raise AppError(401, "用户不存在")
    return user


def require_admin(user: dict) -> dict:
    if user["role"] != "admin":
        raise AppError(403, "需要管理员权限")
    return user


def require_manager(user: dict) -> dict:
    if user["role"] not in {"manager", "admin"}:
        raise AppError(403, "需要主管或管理员权限")
    return user
