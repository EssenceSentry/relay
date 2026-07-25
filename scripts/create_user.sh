#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

: "${EMAIL:?Set EMAIL to the Cognito user email address}"
command -v aws >/dev/null || {
  echo "The AWS CLI is required." >&2
  exit 1
}

POOL_ID="$(python scripts/stack_output.py UserPoolId)"

CREATE_ARGS=(
  "--user-pool-id" "$POOL_ID"
  "--username" "$EMAIL"
  "--user-attributes"
  "Name=email,Value=$EMAIL"
  "Name=email_verified,Value=true"
)
if [[ -n "${PASSWORD:-}" ]]; then
  CREATE_ARGS+=("--message-action" "SUPPRESS")
else
  CREATE_ARGS+=("--desired-delivery-mediums" "EMAIL")
fi

set +e
CREATE_OUTPUT="$(aws cognito-idp admin-create-user \
  "${CREATE_ARGS[@]}" \
  2>&1)"
CREATE_STATUS=$?
set -e

if [[ $CREATE_STATUS -ne 0 ]] && ! grep -q "UsernameExistsException" <<<"$CREATE_OUTPUT"; then
  echo "$CREATE_OUTPUT" >&2
  exit $CREATE_STATUS
fi

if [[ -n "${PASSWORD:-}" ]]; then
  aws cognito-idp admin-set-user-password \
    --user-pool-id "$POOL_ID" \
    --username "$EMAIL" \
    --password "$PASSWORD" \
    --permanent
  echo "Permanent password configured."
else
  echo "Cognito created the user with a temporary password delivered by email."
fi

if [[ "${ADMIN:-0}" == "1" ]]; then
  aws cognito-idp admin-add-user-to-group \
    --user-pool-id "$POOL_ID" \
    --username "$EMAIL" \
    --group-name admins
  echo "Added $EMAIL to the admins group."
fi

echo "User ready: $EMAIL"
