import pytest
from pydantic import ValidationError

from app.schemas import RegisterRequest


def test_registration_requires_strong_password():
    with pytest.raises(ValidationError):
        RegisterRequest(username="new_user", password="abcdefgh", org_name="测试团队")


def test_registration_accepts_valid_payload():
    body = RegisterRequest(
        username="new_user",
        password="abc12345",
        display_name="新用户",
        org_name="测试团队",
    )
    assert body.username == "new_user"
