from __future__ import annotations

from typing import Any, TypeGuard, cast


def is_string_keyed_dict(value: object) -> TypeGuard[dict[str, Any]]:
    """Narrow mappings created by JSON and application-owned DynamoDB data."""
    return isinstance(value, dict)


def is_string_list(value: object) -> TypeGuard[list[str]]:
    """Narrow application-owned JSON arrays containing only strings."""
    if not isinstance(value, list):
        return False
    items = cast(list[object], value)
    return all(isinstance(item, str) for item in items)
