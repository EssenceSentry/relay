from __future__ import annotations

import pytest

from knowledge_core.identity import (
    extract_blend_emails,
    names_are_plausibly_compatible,
    normalize_blend_email,
    normalize_email,
    normalize_name_tokens,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (" Agustin.Sellanes@Blend360.COM ", "agustin.sellanes@blend360.com"),
        ("a+b@blend360.com", "a+b@blend360.com"),
        (" Demo.User@Gmail.COM ", "demo.user@gmail.com"),
    ],
)
def test_normalize_email_accepts_valid_account_addresses(
    value: str,
    expected: str,
) -> None:
    assert normalize_email(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "person",
        "person@localhost",
        ".person@blend360.com",
        "person..name@blend360.com",
        "person)@blend360.com",
    ],
)
def test_normalize_email_rejects_invalid_syntax(
    value: str,
) -> None:
    with pytest.raises(ValueError):
        normalize_email(value)


@pytest.mark.parametrize(
    "value",
    [
        "person@example.com",
        "person@gmail.com",
        "person@sub.blend360.com",
    ],
)
def test_normalize_blend_email_rejects_non_blend_domains(
    value: str,
) -> None:
    with pytest.raises(ValueError):
        normalize_blend_email(value)


def test_extract_blend_emails_handles_case_and_punctuation() -> None:
    text = (
        "Contact Priya.Shah@Blend360.com, or alex+delivery@blend360.com. "
        "Ignore client@example.com and fake@sub.blend360.com."
    )

    assert extract_blend_emails(text) == [
        "alex+delivery@blend360.com",
        "priya.shah@blend360.com",
    ]


def test_name_normalization_handles_diacritics_and_compound_names() -> None:
    assert normalize_name_tokens("María-José de la Peña") == (
        "maria",
        "jose",
        "de",
        "la",
        "pena",
    )
    assert names_are_plausibly_compatible(
        email="maria.pena@blend360.com",
        contributor_name="María José de la Peña",
    )
    assert names_are_plausibly_compatible(
        email="agustin.sellanes@blend360.com",
        contributor_name="Agustín Sellanes Pereira",
    )


def test_name_filter_allows_initials_but_requires_compatible_surname() -> None:
    assert names_are_plausibly_compatible(
        email="m.perez@blend360.com",
        contributor_name="María Pérez",
    )
    assert not names_are_plausibly_compatible(
        email="m.perez@blend360.com",
        contributor_name="María Rodríguez",
    )
    assert not names_are_plausibly_compatible(
        email="maria.perez@gmail.com",
        contributor_name="María Pérez",
    )
