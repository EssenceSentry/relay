from __future__ import annotations

import re
import unicodedata

BLEND_EMAIL_DOMAIN = "blend360.com"
_EMAIL_PATTERN = re.compile(
    r"(?<![A-Z0-9._%+-])"
    r"([A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@blend360\.com)"
    r"(?![A-Z0-9-]|\.[A-Z0-9])",
    re.IGNORECASE,
)
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def normalize_email(value: str) -> str:
    email = value.strip().casefold()
    local_part, separator, domain = email.rpartition("@")
    if not separator or not local_part or domain != BLEND_EMAIL_DOMAIN:
        raise ValueError(
            f"Email must use the exact @{BLEND_EMAIL_DOMAIN} domain"
        )
    if len(email) > 320 or _EMAIL_PATTERN.fullmatch(email) is None:
        raise ValueError("Email address is not syntactically valid")
    if local_part.startswith(".") or local_part.endswith(".") or ".." in local_part:
        raise ValueError("Email address is not syntactically valid")
    return email


def is_blend_email(value: str) -> bool:
    try:
        normalize_email(value)
    except ValueError:
        return False
    return True


def extract_blend_emails(text: str) -> list[str]:
    matches: set[str] = set()
    for match in _EMAIL_PATTERN.finditer(text):
        try:
            matches.add(normalize_email(match.group(1)))
        except ValueError:
            continue
    return sorted(matches)


def normalize_name_tokens(value: str) -> tuple[str, ...]:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    ascii_value = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return tuple(_TOKEN_PATTERN.findall(ascii_value))


def email_name_tokens(email: str) -> tuple[str, ...]:
    normalized = normalize_email(email)
    local_part = normalized.split("@", maxsplit=1)[0].split("+", maxsplit=1)[0]
    return normalize_name_tokens(local_part)


def names_are_plausibly_compatible(
    *,
    email: str,
    contributor_name: str,
) -> bool:
    email_tokens = email_name_tokens(email)
    candidate_tokens = normalize_name_tokens(contributor_name)
    if len(email_tokens) < 2 or len(candidate_tokens) < 2:
        return False
    if email_tokens[-1] not in candidate_tokens[1:]:
        return False
    return any(
        _given_tokens_compatible(email_token, candidate_token)
        for email_token in email_tokens[:-1]
        for candidate_token in candidate_tokens[:-1]
    )


def candidate_surname(value: str) -> str | None:
    tokens = normalize_name_tokens(value)
    return tokens[-1] if len(tokens) >= 2 else None


def _given_tokens_compatible(email_token: str, candidate_token: str) -> bool:
    if email_token == candidate_token:
        return True
    if len(email_token) == 1:
        return candidate_token.startswith(email_token)
    return len(email_token) >= 3 and candidate_token.startswith(email_token)
