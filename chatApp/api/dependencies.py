from dataclasses import dataclass
from hmac import compare_digest

from fastapi import Depends, Header, HTTPException

from core import config


@dataclass(frozen=True, slots=True)
class CurrentUser:
    user_id: str
    role: str
    building_code: str


def verify_internal_api_key(
    x_internal_api_key: str | None = Header(default=None),
) -> None:
    expected = config.INTERNAL_API_KEY
    if not expected:
        raise HTTPException(status_code=503, detail="INTERNAL_API_KEY chưa được cấu hình.")
    if not x_internal_api_key or not compare_digest(x_internal_api_key, expected):
        raise HTTPException(status_code=403, detail="Internal API key không hợp lệ.")


def get_current_user(
    x_user_id: str | None = Header(default=None),
    x_user_role: str | None = Header(default=None),
    x_building_code: str | None = Header(default=None),
    x_internal_api_key: str | None = Header(default=None),
) -> CurrentUser:
    verify_internal_api_key(x_internal_api_key)
    if not x_user_id or not x_user_role or not x_building_code:
        raise HTTPException(status_code=401, detail="Thiếu trusted user headers.")
    return CurrentUser(
        user_id=x_user_id.strip(),
        role=x_user_role.strip(),
        building_code=x_building_code.strip().upper(),
    )


def get_optional_current_user(
    x_user_id: str | None = Header(default=None),
    x_user_role: str | None = Header(default=None),
    x_building_code: str | None = Header(default=None),
    x_internal_api_key: str | None = Header(default=None),
) -> CurrentUser | None:
    supplied = any((x_user_id, x_user_role, x_building_code, x_internal_api_key))
    if not supplied and config.ALLOW_LEGACY_UNAUTHENTICATED_CHAT:
        return None
    verify_internal_api_key(x_internal_api_key)
    if not x_user_id or not x_user_role or not x_building_code:
        raise HTTPException(status_code=401, detail="Thiếu trusted user headers.")
    return CurrentUser(
        user_id=x_user_id.strip(),
        role=x_user_role.strip(),
        building_code=x_building_code.strip().upper(),
    )


def require_document_upload_permission(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    if user.role.lower() not in {"admin", "quanly", "manager"}:
        raise HTTPException(status_code=403, detail="Không có quyền quản lý tài liệu.")
    return user


def assert_building_access(user: CurrentUser, building_code: str) -> None:
    if user.building_code != building_code.strip().upper():
        raise HTTPException(status_code=403, detail="Không có quyền truy cập tòa nhà.")
