#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MCP_URL="$(python scripts/stack_output.py McpUrl)"
CONNECT_URL="$(python scripts/stack_output.py McpConnectUrl)"
AUTH_METADATA_URL="$(
  python scripts/stack_output.py McpAuthorizationServerMetadataUrl
)"
MCP_AUTH_ENABLED="$(python scripts/stack_output.py McpAuthEnabled 2>/dev/null || echo true)"

cat <<EOF
Remote MCP endpoint:
  $MCP_URL

OAuth discovery:
  $AUTH_METADATA_URL

Shareable connection page:
  $CONNECT_URL

EOF

if [[ "$MCP_AUTH_ENABLED" == "true" ]]; then
  cat <<EOF
Codex:
  codex mcp add blend-knowledge --url '$MCP_URL'
  codex mcp login blend-knowledge

Claude Code:
  claude mcp add --transport http --scope user blend-knowledge '$MCP_URL'
  Then run /mcp and complete the browser login.

ChatGPT or Claude:
  Add the remote MCP URL as a custom plugin or connector and select Connect.
EOF
else
  cat <<EOF
Authentication:
  Disabled for the public hackathon deployment.

Codex:
  codex mcp add blend-knowledge --url '$MCP_URL'

Claude Code:
  claude mcp add --transport http --scope user blend-knowledge '$MCP_URL'

ChatGPT or Claude:
  Add the remote MCP URL as a Streamable HTTP custom plugin or connector.
EOF
fi
