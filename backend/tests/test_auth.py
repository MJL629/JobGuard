import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.auth import create_access_token, get_current_user_id


@pytest.mark.asyncio
async def test_auth_rejects_missing_credentials():
    with pytest.raises(HTTPException) as exc:
        await get_current_user_id(request=None, credentials=None)
    assert exc.value.status_code == 401
    assert "登录" in exc.value.detail


@pytest.mark.asyncio
async def test_auth_reads_user_from_access_token():
    token = create_access_token(42, "tester")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    user_id = await get_current_user_id(request=None, credentials=credentials)
    assert user_id == 42
