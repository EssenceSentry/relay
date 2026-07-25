#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

: "${OPENAI_API_KEY:?Set OPENAI_API_KEY before running this script}"
command -v aws >/dev/null || {
  echo "The AWS CLI is required." >&2
  exit 1
}

SECRET_ARN="$(python scripts/stack_output.py OpenAISecretArn)"
SECRET_JSON="$(python - <<'PY'
import json
import os

print(json.dumps({"api_key": os.environ["OPENAI_API_KEY"]}))
PY
)"

aws secretsmanager put-secret-value \
  --secret-id "$SECRET_ARN" \
  --secret-string "$SECRET_JSON" \
  >/dev/null

echo "OpenAI API key stored in Secrets Manager."
