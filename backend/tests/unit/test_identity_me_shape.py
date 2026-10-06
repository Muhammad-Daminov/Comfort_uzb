"""Unit test for `MeResponse`'s shape — pure Pydantic model, no DB needed."""
from app.domains.identity.router import MeResponse


def test_me_response_accepts_all_user_fields():
    model = MeResponse(
        id=1,
        telegram_id=123456,
        first_name="Ali",
        last_name=None,
        username="ali",
        role="USER",
        phone=None,
        status="ACTIVE",
    )
    assert model.id == 1
    assert model.phone is None
    assert model.role == "USER"
