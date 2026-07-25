#!/usr/bin/env python3
"""Build the static cross-client Blend Project Knowledge plugin bundle."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "blend-project-knowledge"
MARKETPLACE_NAME = "blend360-project-knowledge"
PLUGIN_SOURCE = ROOT / "plugins" / PLUGIN_NAME
DOWNLOADS_DIR = ROOT / "frontend" / "downloads"
ARCHIVE_PATH = DOWNLOADS_DIR / f"{PLUGIN_NAME}-bundle.zip"
CHECKSUM_PATH = DOWNLOADS_DIR / f"{PLUGIN_NAME}-bundle.sha256"


def _read_plugin_manifest() -> dict[str, object]:
    manifest_path = PLUGIN_SOURCE / ".codex-plugin" / "plugin.json"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _codex_marketplace(_version: str) -> dict[str, object]:
    return {
        "name": MARKETPLACE_NAME,
        "interface": {"displayName": "Blend360 Project Knowledge"},
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
            "Blend360 project knowledge tools and evidence-backed dossier workflows."
        ),
        "plugins": [
            {
                "name": PLUGIN_NAME,
                "source": f"./plugins/{PLUGIN_NAME}",
                "description": (
                    "Search Blend project evidence and create source-cited "
                    "project dossiers."
                ),
                "version": version,
            }
        ],
    }


def _install_readme(version: str) -> str:
    return f"""# Blend Project Knowledge plugin bundle

Version: {version}

This bundle contains the same remote MCP connection and project-dossier skill
for Codex and Claude Code. It connects to:

https://essencesentry.shop/mcp/

## Codex

Extract this archive, then run:

```bash
codex plugin marketplace add /absolute/path/to/blend-project-knowledge-bundle
codex plugin add {PLUGIN_NAME}@{MARKETPLACE_NAME}
```

Start a new thread and invoke `$create-project-dossier`, or ask for a project
dossier, sales brief, success story, or case study.

## Claude Code

Extract this archive, then run:

```bash
claude plugin marketplace add /absolute/path/to/blend-project-knowledge-bundle
claude plugin install {PLUGIN_NAME}@{MARKETPLACE_NAME}
```

Run `/reload-plugins`, then invoke
`/{PLUGIN_NAME}:create-project-dossier` or ask Claude for a project dossier,
sales brief, success story, or case study.

For a temporary Claude Code session without marketplace installation:

```bash
claude --plugin-dir /absolute/path/to/blend-project-knowledge-bundle/plugins/{PLUGIN_NAME}
```

The current hackathon MCP is public. When authentication is re-enabled, your
client may prompt you to complete the configured browser login.
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


def main() -> None:
    manifest = _read_plugin_manifest()
    version = str(manifest["version"])
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="blend-plugin-") as temp:
        bundle_root = Path(temp) / "blend-project-knowledge-bundle"
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

    digest = hashlib.sha256(ARCHIVE_PATH.read_bytes()).hexdigest()
    CHECKSUM_PATH.write_text(
        f"{digest}  {ARCHIVE_PATH.name}\n",
        encoding="utf-8",
    )
    print(f"Built {ARCHIVE_PATH.relative_to(ROOT)}")
    print(f"SHA-256 {digest}")


if __name__ == "__main__":
    main()
