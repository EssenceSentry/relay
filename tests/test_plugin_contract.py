from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_PLUGIN = _ROOT / "plugins" / "relay"


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

    assert codex["version"] == "1.0.3"
    assert claude["version"] == codex["version"]
    assert marketplace["plugins"][0]["version"] == codex["version"]
