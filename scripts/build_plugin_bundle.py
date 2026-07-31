#!/usr/bin/env python3
"""Build deterministic Relay plugin and skill download archives."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "relay"
MARKETPLACE_NAME = "relay"
PLUGIN_SOURCE = ROOT / "plugins" / PLUGIN_NAME
DOWNLOADS_DIR = ROOT / "frontend" / "downloads"
ARCHIVE_PATH = DOWNLOADS_DIR / f"{PLUGIN_NAME}-bundle.zip"
CHECKSUM_PATH = DOWNLOADS_DIR / f"{PLUGIN_NAME}-bundle.sha256"
DOWNLOAD_MANIFEST_PATH = DOWNLOADS_DIR / "relay-downloads.json"
SKILL_DESCRIPTIONS = {
    "manage-project-knowledge": (
        "Safe Relay project, retrieval, upload, inbox, and question workflows."
    ),
    "create-project-dossier": (
        "Evidence-first Relay dossiers and sales briefs with inline citations."
    ),
}


def _read_plugin_manifest() -> dict[str, object]:
    manifest_path = PLUGIN_SOURCE / ".codex-plugin" / "plugin.json"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _codex_marketplace(_version: str) -> dict[str, object]:
    return {
        "name": MARKETPLACE_NAME,
        "interface": {"displayName": "Relay"},
        "plugins": [
            {
                "name": PLUGIN_NAME,
                "source": {
                    "source": "local",
                    "path": f"./plugins/{PLUGIN_NAME}",
                },
                "policy": {
                    "installation": "AVAILABLE",
                    "authentication": "ON_INSTALL",
                },
                "category": "Productivity",
            }
        ],
    }


def _claude_marketplace(version: str) -> dict[str, object]:
    return {
        "$schema": "https://json.schemastore.org/claude-code-marketplace.json",
        "name": MARKETPLACE_NAME,
        "owner": {"name": "Blend360"},
        "description": (
            "Relay project knowledge tools and evidence-backed dossier workflows."
        ),
        "plugins": [
            {
                "name": PLUGIN_NAME,
                "source": f"./plugins/{PLUGIN_NAME}",
                "description": (
                    "Search and manage Relay project knowledge with cited dossiers."
                ),
                "version": version,
            }
        ],
    }


def _install_readme(version: str) -> str:
    return f"""# Relay plugin bundle

Version: {version}

Relay normally provides its current workflows directly through the remote MCP.
This compatibility bundle contains that authenticated MCP connection plus the
project-operations and source-cited dossier skills for Codex and Claude Code.
It connects to:

https://essencesentry.shop/mcp/

## Codex

Extract this archive, then run:

```bash
codex plugin marketplace add /absolute/path/to/relay-bundle
codex plugin add {PLUGIN_NAME}@{MARKETPLACE_NAME}
```

Start a new thread and invoke `$manage-project-knowledge` for project
operations or `$create-project-dossier` for a dossier, sales brief, success
story, or case study.

## Claude Code

Extract this archive, then run:

```bash
claude plugin marketplace add /absolute/path/to/relay-bundle
claude plugin install {PLUGIN_NAME}@{MARKETPLACE_NAME}
```

Run `/reload-plugins`, then invoke
`/{PLUGIN_NAME}:manage-project-knowledge` for project operations or
`/{PLUGIN_NAME}:create-project-dossier` for a dossier, sales brief, success
story, or case study.

For a temporary Claude Code session without marketplace installation:

```bash
claude --plugin-dir /absolute/path/to/relay-bundle/plugins/{PLUGIN_NAME}
```

The MCP requires a verified Relay login. Your client opens the configured
browser authorization flow when it connects.
"""


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _archive_tree(source: Path, destination: Path) -> None:
    root_name = source.name
    with zipfile.ZipFile(
        destination,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            relative = Path(root_name) / path.relative_to(source)
            info = zipfile.ZipInfo.from_file(path, arcname=relative.as_posix())
            info.date_time = (2026, 7, 25, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compresslevel=9)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_checksum(path: Path, *, digest: str, filename: str) -> None:
    path.write_text(f"{digest}  {filename}\n", encoding="utf-8")


def _artifact(
    *,
    name: str,
    description: str,
    path: Path,
) -> dict[str, str]:
    return {
        "name": name,
        "description": description,
        "filename": path.name,
        "sha256": _sha256(path),
    }


def main() -> None:
    manifest = _read_plugin_manifest()
    version = str(manifest["version"])
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="relay-plugin-") as temp:
        bundle_root = Path(temp) / "relay-bundle"
        plugin_target = bundle_root / "plugins" / PLUGIN_NAME
        shutil.copytree(PLUGIN_SOURCE, plugin_target)
        _write_json(
            bundle_root / ".agents" / "plugins" / "marketplace.json",
            _codex_marketplace(version),
        )
        _write_json(
            bundle_root / ".claude-plugin" / "marketplace.json",
            _claude_marketplace(version),
        )
        (bundle_root / "README.md").write_text(
            _install_readme(version),
            encoding="utf-8",
        )
        _archive_tree(bundle_root, ARCHIVE_PATH)

    plugin_artifact = _artifact(
        name="relay",
        description=(
            "Complete Relay compatibility bundle with MCP configuration and "
            "both skills."
        ),
        path=ARCHIVE_PATH,
    )
    _write_checksum(
        CHECKSUM_PATH,
        digest=plugin_artifact["sha256"],
        filename=ARCHIVE_PATH.name,
    )

    skill_artifacts: list[dict[str, str]] = []
    for skill_name, description in SKILL_DESCRIPTIONS.items():
        skill_path = PLUGIN_SOURCE / "skills" / skill_name
        archive_path = DOWNLOADS_DIR / f"{skill_name}.zip"
        checksum_path = DOWNLOADS_DIR / f"{skill_name}.sha256"
        _archive_tree(skill_path, archive_path)
        artifact = _artifact(
            name=skill_name,
            description=description,
            path=archive_path,
        )
        _write_checksum(
            checksum_path,
            digest=artifact["sha256"],
            filename=archive_path.name,
        )
        skill_artifacts.append(artifact)

    _write_json(
        DOWNLOAD_MANIFEST_PATH,
        {
            "version": version,
            "plugin_bundle": plugin_artifact,
            "skills": skill_artifacts,
        },
    )
    print(f"Built {ARCHIVE_PATH.relative_to(ROOT)}")
    for artifact in skill_artifacts:
        print(f"Built frontend/downloads/{artifact['filename']}")
    print(f"SHA-256 {plugin_artifact['sha256']}")


if __name__ == "__main__":
    main()
