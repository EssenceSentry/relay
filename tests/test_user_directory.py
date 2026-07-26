from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.application import KnowledgeApplication
from app.auth import Principal


class FakeRepository:
    def list_user_profiles(self) -> list[dict[str, Any]]:
        return [
            {
                "display_name": "Agustín Sellanes",
                "email": "essence.sentry@gmail.com",
                "email_verified": True,
                "identity_source": "COGNITO",
            },
            {
                "display_name": "Agustina Sellanes",
                "email": "agustina.sellanes@blend360.com",
                "email_verified": True,
                "identity_source": "COGNITO",
            },
            {
                "display_name": "Unverified Person",
                "email": "unverified@blend360.com",
                "email_verified": False,
                "identity_source": "COGNITO",
            },
        ]


def _principal() -> Principal:
    return Principal(
        subject="user-1",
        email="reader@gmail.com",
        groups=frozenset(),
        claims={},
    )


def _application() -> KnowledgeApplication:
    return KnowledgeApplication(
        SimpleNamespace(repository=FakeRepository()),  # pyright: ignore[reportArgumentType]
    )


def test_directory_normalizes_diacritics_and_returns_exact_name() -> None:
    matches = _application().search_user_directory(
        "agustin sellanes",
        principal=_principal(),
    )

    assert matches == [
        {
            "display_name": "Agustín Sellanes",
            "email": "essence.sentry@gmail.com",
            "identity_source": "COGNITO",
            "match_type": "EXACT_NAME",
        }
    ]


def test_directory_exact_email_resolves_the_verified_profile() -> None:
    matches = _application().search_user_directory(
        "Essence.Sentry@Gmail.COM",
        principal=_principal(),
    )

    assert len(matches) == 1
    assert matches[0]["display_name"] == "Agustín Sellanes"
    assert matches[0]["match_type"] == "EXACT_EMAIL"


def test_directory_never_returns_unverified_profiles() -> None:
    matches = _application().search_user_directory(
        "Unverified Person",
        principal=_principal(),
    )

    assert matches == []
