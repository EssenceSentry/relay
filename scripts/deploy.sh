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
        MCP_PUBLIC_BASE_URL | OPENSEARCH_ADMIN_PRINCIPAL_ARN | \
        INITIAL_ADMIN_EMAILS | NAME_INVITATIONS_ENABLED | \
        COGNITO_USE_SES_EMAIL)
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
command -v aws >/dev/null || {
  echo "The AWS CLI is required to resolve the deployment account." >&2
  exit 1
}

DEPLOY_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
export CDK_DEFAULT_REGION="${CDK_DEFAULT_REGION:-$DEPLOY_REGION}"
if [[ -z "${CDK_DEFAULT_ACCOUNT:-}" ]]; then
  CDK_DEFAULT_ACCOUNT="$(
    aws sts get-caller-identity --query Account --output text
  )"
  export CDK_DEFAULT_ACCOUNT
fi

CDK_CONTEXT=()
CDK_ASSEMBLY_DIR="$(mktemp -d /tmp/relay-cdk.XXXXXX)"
cleanup_assembly() {
  rm -rf "$CDK_ASSEMBLY_DIR"
}
trap cleanup_assembly EXIT

if [[ -n "${EMAIL_DOMAIN:-}" ]]; then
  CDK_CONTEXT+=("-c" "email_domain=${EMAIL_DOMAIN}")
fi
if [[ -n "${EMAIL_SENDER_LOCAL_PART:-}" ]]; then
  CDK_CONTEXT+=("-c" "email_sender_local_part=${EMAIL_SENDER_LOCAL_PART}")
fi
if [[ -n "${MCP_AUTH_ENABLED:-}" ]]; then
  CDK_CONTEXT+=("-c" "mcp_auth_enabled=${MCP_AUTH_ENABLED}")
fi
if [[ -n "${INITIAL_ADMIN_EMAILS:-}" ]]; then
  CDK_CONTEXT+=("-c" "initial_admin_emails=${INITIAL_ADMIN_EMAILS}")
fi
if [[ -n "${NAME_INVITATIONS_ENABLED:-}" ]]; then
  CDK_CONTEXT+=(
    "-c"
    "name_invitations_enabled=${NAME_INVITATIONS_ENABLED}"
  )
fi
if [[ -n "${COGNITO_USE_SES_EMAIL:-}" ]]; then
  CDK_CONTEXT+=(
    "-c"
    "cognito_use_ses_email=${COGNITO_USE_SES_EMAIL}"
  )
fi
if [[ -n "${OPENSEARCH_ADMIN_PRINCIPAL_ARN:-}" ]]; then
  CDK_CONTEXT+=(
    "-c"
    "opensearch_admin_principal_arn=${OPENSEARCH_ADMIN_PRINCIPAL_ARN}"
  )
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
uv run python scripts/build_plugin_bundle.py
if ! aws cloudformation describe-stacks \
  --stack-name CDKToolkit \
  --region "$CDK_DEFAULT_REGION" >/dev/null 2>&1; then
  npx --yes aws-cdk@latest bootstrap \
    "aws://${CDK_DEFAULT_ACCOUNT}/${CDK_DEFAULT_REGION}"
fi

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
    "--output" "$CDK_ASSEMBLY_DIR"
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
echo "  PASSWORD='...' uv run python scripts/create_user.py you@blend360.com --admin"
echo "  uv run python scripts/configure_sso.py microsoft --tenant-id ... --client-id ..."
if [[ -n "${EMAIL_DOMAIN:-}" ]]; then
  echo "  python scripts/email_setup_status.py"
  echo "  python scripts/verify_ses_recipients.py expert@blend360.com"
fi
echo "  ./scripts/show_mcp_connection.sh"
