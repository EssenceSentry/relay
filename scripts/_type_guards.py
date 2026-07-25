from __future__ import annotations

from typing import Any, TypeGuard


def is_string_keyed_dict(value: object) -> TypeGuard[dict[str, Any]]:
    """Narrow mappings created by JSON and application-owned DynamoDB data."""
    return isinstance(value, dict)
