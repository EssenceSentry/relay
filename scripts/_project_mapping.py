from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from _type_guards import is_string_keyed_dict, is_string_list


@dataclass(frozen=True)
class ProjectFileGroup:
    key: str
    title: str
    files: tuple[str, ...]
    description: str | None = None


def _normalized_relative_name(value: str) -> str:
    normalized = PurePosixPath(value.strip().replace("\\", "/")).as_posix()
    if normalized in {"", "."} or normalized.startswith("../"):
        raise ValueError(f"Invalid mapped file path: {value!r}")
    return normalized


def _string_list(value: Any, *, field: str) -> tuple[str, ...]:
    if not is_string_list(value) or not value:
        raise ValueError(f"{field} must be a non-empty list of file names")
    files: list[str] = []
    for item in value:
        if not item.strip():
            raise ValueError(f"{field} contains an invalid file name")
        files.append(_normalized_relative_name(item))
    if len(files) != len(set(files)):
        raise ValueError(f"{field} contains duplicate file names")
    return tuple(files)


def load_project_mapping(path: Path) -> tuple[ProjectFileGroup, ...]:
    try:
        payload: Any = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise ValueError(f"Project mapping not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Project mapping is invalid JSON: {path}") from exc
    if not is_string_keyed_dict(payload) or not payload:
        raise ValueError("Project mapping must be a non-empty JSON object")

    groups: list[ProjectFileGroup] = []
    assigned_files: dict[str, str] = {}
    titles: dict[str, str] = {}
    for raw_key, raw_group in payload.items():
        key = raw_key.strip()
        if not key:
            raise ValueError("Project mapping contains an empty project key")
        if not is_string_keyed_dict(raw_group):
            raise ValueError(f"Project {key!r} must be a JSON object")
        raw_title = raw_group.get("title")
        if not isinstance(raw_title, str) or not raw_title.strip():
            raise ValueError(f"Project {key!r} requires a non-empty title")
        title = raw_title.strip()
        folded_title = title.casefold()
        if previous_key := titles.get(folded_title):
            raise ValueError(
                f"Projects {previous_key!r} and {key!r} share title {title!r}"
            )
        titles[folded_title] = key

        files = _string_list(
            raw_group.get("files"),
            field=f"Project {key!r} files",
        )
        for file_name in files:
            folded_file = file_name.casefold()
            if previous_key := assigned_files.get(folded_file):
                raise ValueError(
                    f"File {file_name!r} is assigned to both "
                    f"{previous_key!r} and {key!r}"
                )
            assigned_files[folded_file] = key

        raw_description = raw_group.get("description")
        if raw_description is not None and not isinstance(
            raw_description,
            str,
        ):
            raise ValueError(
                f"Project {key!r} description must be a string or null"
            )
        description = (
            raw_description.strip()
            if isinstance(raw_description, str) and raw_description.strip()
            else None
        )
        groups.append(
            ProjectFileGroup(
                key=key,
                title=title,
                files=files,
                description=description,
            )
        )
    return tuple(groups)


def resolve_mapped_files(
    *,
    source: Path,
    available_files: list[Path],
    groups: tuple[ProjectFileGroup, ...],
) -> dict[Path, ProjectFileGroup]:
    by_relative = {
        path.relative_to(source).as_posix().casefold(): path
        for path in available_files
    }
    by_basename: dict[str, list[Path]] = {}
    for path in available_files:
        by_basename.setdefault(path.name.casefold(), []).append(path)

    resolved: dict[Path, ProjectFileGroup] = {}
    missing: list[str] = []
    ambiguous: list[str] = []
    for group in groups:
        for mapped_name in group.files:
            folded = mapped_name.casefold()
            path = by_relative.get(folded)
            if path is None and "/" not in mapped_name:
                basename_matches = by_basename.get(folded, [])
                if len(basename_matches) == 1:
                    path = basename_matches[0]
                elif len(basename_matches) > 1:
                    ambiguous.append(mapped_name)
                    continue
            if path is None:
                missing.append(mapped_name)
                continue
            previous = resolved.get(path)
            if previous is not None and previous.key != group.key:
                raise ValueError(
                    f"File {path.relative_to(source)} resolves to both "
                    f"{previous.key!r} and {group.key!r}"
                )
            resolved[path] = group

    problems: list[str] = []
    if missing:
        preview = ", ".join(repr(name) for name in missing[:5])
        suffix = "" if len(missing) <= 5 else f", and {len(missing) - 5} more"
        problems.append(f"missing mapped files: {preview}{suffix}")
    if ambiguous:
        preview = ", ".join(repr(name) for name in ambiguous[:5])
        suffix = (
            "" if len(ambiguous) <= 5 else f", and {len(ambiguous) - 5} more"
        )
        problems.append(f"ambiguous mapped basenames: {preview}{suffix}")
    if problems:
        raise ValueError("; ".join(problems))
    return resolved


def groups_by_key(
    groups: tuple[ProjectFileGroup, ...],
) -> dict[str, ProjectFileGroup]:
    return {group.key: group for group in groups}
