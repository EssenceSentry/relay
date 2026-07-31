from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_PLUGIN = _ROOT / "plugins" / "relay"
_DOWNLOADS = _ROOT / "frontend" / "downloads"


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_project_skill_requires_proactive_missing_evidence_handoff() -> None:
    skill = (
        _PLUGIN / "skills" / "manage-project-knowledge" / "SKILL.md"
    ).read_text(encoding="utf-8")

    for requirement in (
        "do not\n  stop after reporting the gap",
        "you **must** call\n  `get_project` and `list_project_collaborators`",
        "suggest the verified project author first",
        "offer to draft a question",
        "Never call\n`create_project_question` until the user confirms",
    ):
        assert requirement in skill


def test_relay_plugin_manifests_publish_the_same_version() -> None:
    codex = _json(_PLUGIN / ".codex-plugin" / "plugin.json")
    claude = _json(_PLUGIN / ".claude-plugin" / "plugin.json")
    marketplace = _json(_ROOT / ".claude-plugin" / "marketplace.json")

    assert codex["version"] == "1.0.4"
    assert claude["version"] == codex["version"]
    assert marketplace["plugins"][0]["version"] == codex["version"]


def test_download_manifest_and_checksums_match_archives() -> None:
    manifest = _json(_DOWNLOADS / "relay-downloads.json")
    codex = _json(_PLUGIN / ".codex-plugin" / "plugin.json")

    assert manifest["version"] == codex["version"]
    artifacts = [manifest["plugin_bundle"], *manifest["skills"]]
    for artifact in artifacts:
        archive_path = _DOWNLOADS / artifact["filename"]
        digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        checksum_path = archive_path.with_suffix(".sha256")
        assert digest == artifact["sha256"]
        assert checksum_path.read_text(encoding="utf-8") == (
            f"{digest}  {archive_path.name}\n"
        )


def test_individual_skill_archives_preserve_portable_skill_roots() -> None:
    manifest = _json(_DOWNLOADS / "relay-downloads.json")

    for artifact in manifest["skills"]:
        skill_name = artifact["name"]
        source = _PLUGIN / "skills" / skill_name
        archive_path = _DOWNLOADS / artifact["filename"]
        source_files = {
            path.relative_to(source).as_posix(): path.read_bytes()
            for path in source.rglob("*")
            if path.is_file()
        }
        with zipfile.ZipFile(archive_path) as archive:
            archived_files = {
                name.removeprefix(f"{skill_name}/"): archive.read(name)
                for name in archive.namelist()
            }
        assert archived_files == source_files
