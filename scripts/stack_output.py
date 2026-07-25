#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _type_guards import is_string_keyed_dict


def load_outputs(path: Path, stack: str | None) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise SystemExit(
            f"Outputs file not found: {path}. Deploy with --outputs-file first."
        ) from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Outputs file is not valid JSON: {path}") from exc

    if not is_string_keyed_dict(payload) or not payload:
        raise SystemExit(f"Outputs file contains no stacks: {path}")
    if stack:
        selected = payload.get(stack)
        if not is_string_keyed_dict(selected):
            available = ", ".join(sorted(payload))
            raise SystemExit(f"Unknown stack {stack!r}. Available: {available}")
        return selected
    if len(payload) != 1:
        available = ", ".join(sorted(payload))
        raise SystemExit(
            "More than one stack is present; pass --stack. "
            f"Available: {available}"
        )
    selected = next(iter(payload.values()))
    if not is_string_keyed_dict(selected):
        raise SystemExit("Unexpected CDK outputs shape")
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description="Read a CDK stack output")
    parser.add_argument("key", help="CloudFormation output key")
    parser.add_argument(
        "--file",
        type=Path,
        default=Path("cdk-outputs.json"),
        help="CDK outputs file (default: cdk-outputs.json)",
    )
    parser.add_argument("--stack", help="Stack key in the outputs file")
    args = parser.parse_args()

    outputs = load_outputs(args.file, args.stack)
    value = outputs.get(args.key)
    if value is None:
        available = ", ".join(sorted(outputs))
        raise SystemExit(f"Unknown output {args.key!r}. Available: {available}")
    if isinstance(value, (dict, list)):
        print(json.dumps(value))
    else:
        print(value)


if __name__ == "__main__":
    main()
