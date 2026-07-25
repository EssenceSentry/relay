#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Load only non-secret deployment settings from the ignored local .env file.
# Explicit shell environment values continue to take precedence.
if [[ -f "$ROOT/.env" ]]; then
  while IFS='=' read -r key value; do
    value="${value%$'\r'}"
    value="${value#\"}"
    value="${value%\"}"
    value="${value#\'}"
    value="${value%\'}"
    case "$key" in
      AWS_PROFILE | AWS_REGION | AWS_DEFAULT_REGION | EMAIL_DOMAIN | \
        EMAIL_SENDER_LOCAL_PART | MICROSOFT_SSO | \
        MICROSOFT_SSO_SECRET_NAME | MCP_AUTH_ENABLED | PUBLIC_DOMAIN | \
        MCP_PUBLIC_BASE_URL)
        if [[ -z "${!key:-}" ]]; then
          printf -v "$key" "%s" "$value"
          export "$key"
        fi
        ;;
    esac
  done <"$ROOT/.env"
fi

command -v uv >/dev/null || {
  echo "uv is required: https://docs.astral.sh/uv/" >&2
  exit 1
}
command -v npx >/dev/null || {
  echo "Node.js/npx is required for the AWS CDK CLI." >&2
  exit 1
}

CDK_CONTEXT=()
if [[ -n "${EMAIL_DOMAIN:-}" ]]; then
  CDK_CONTEXT+=("-c" "email_domain=${EMAIL_DOMAIN}")
fi
if [[ -n "${EMAIL_SENDER_LOCAL_PART:-}" ]]; then
  CDK_CONTEXT+=("-c" "email_sender_local_part=${EMAIL_SENDER_LOCAL_PART}")
fi
if [[ -n "${MCP_AUTH_ENABLED:-}" ]]; then
  CDK_CONTEXT+=("-c" "mcp_auth_enabled=${MCP_AUTH_ENABLED}")
fi
if [[ -n "${PUBLIC_DOMAIN:-}" ]]; then
  CDK_CONTEXT+=("-c" "public_domain=${PUBLIC_DOMAIN}")
fi
if [[ "${MICROSOFT_SSO:-0}" == "1" ]]; then
  CDK_CONTEXT+=("-c" "microsoft_sso=true")
  CDK_CONTEXT+=(
    "-c"
    "microsoft_sso_secret_name=${MICROSOFT_SSO_SECRET_NAME:-blend-knowledge/sso/microsoft}"
  )
fi

uv sync --all-groups
npx --yes aws-cdk@latest bootstrap

PUBLIC_BASE_URL="${MCP_PUBLIC_BASE_URL:-}"
if [[ -z "$PUBLIC_BASE_URL" && -n "${PUBLIC_DOMAIN:-}" ]]; then
  PUBLIC_BASE_URL="https://${PUBLIC_DOMAIN}/"
fi
if [[ -z "$PUBLIC_BASE_URL" && -f cdk-outputs.json ]]; then
  PUBLIC_BASE_URL="$(python scripts/stack_output.py FrontendUrl 2>/dev/null || true)"
fi

deploy_stack() {
  local public_base_url="$1"
  shift
  local deploy_args=(
    "--require-approval" "never"
    "--outputs-file" "cdk-outputs.json"
  )
  if [[ ${#CDK_CONTEXT[@]} -gt 0 ]]; then
    deploy_args+=("${CDK_CONTEXT[@]}")
  fi
  if [[ -n "$public_base_url" ]]; then
    deploy_args+=("-c" "mcp_public_base_url=${public_base_url}")
  fi
  npx --yes aws-cdk@latest deploy "${deploy_args[@]}" "$@"
}

deploy_stack "$PUBLIC_BASE_URL" "$@"
if [[ -z "$PUBLIC_BASE_URL" ]]; then
  PUBLIC_BASE_URL="$(python scripts/stack_output.py FrontendUrl)"
  echo
  echo "Finalizing OAuth and CORS with CloudFront origin: $PUBLIC_BASE_URL"
  deploy_stack "$PUBLIC_BASE_URL" "$@"
fi

echo
echo "Deployment complete. Next steps:"
echo "  OPENAI_API_KEY=... ./scripts/configure_openai.sh"
echo "  PASSWORD='...' uv run python scripts/create_user.py you@example.com --admin"
echo "  uv run python scripts/configure_sso.py microsoft --tenant-id ... --client-id ..."
if [[ -n "${EMAIL_DOMAIN:-}" ]]; then
  echo "  python scripts/email_setup_status.py"
  echo "  python scripts/verify_ses_recipients.py expert@example.com"
fi
echo "  ./scripts/show_mcp_connection.sh"
