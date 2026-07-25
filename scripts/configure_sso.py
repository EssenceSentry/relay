#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from _bootstrap_aws import create_session, load_stack_context, require_output
from botocore.exceptions import ClientError
from mypy_boto3_secretsmanager import SecretsManagerClient

SECRET_NAMES = {"microsoft": "blend-knowledge/sso/microsoft"}


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Store Microsoft Entra OAuth credentials for future Blend SSO. "
            "Secrets are never printed or written locally."
        )
    )
    parser.add_argument("provider", choices=sorted(SECRET_NAMES))
    parser.add_argument(
        "--client-id",
        default=os.environ.get("SSO_CLIENT_ID"),
        help="OAuth application client ID (or set SSO_CLIENT_ID).",
    )
    parser.add_argument(
        "--tenant-id",
        default=os.environ.get("MICROSOFT_TENANT_ID"),
        help="Microsoft Entra tenant ID.",
    )
    parser.add_argument(
        "--client-secret-env",
        default="SSO_CLIENT_SECRET",
        help="Environment variable containing the OAuth client secret.",
    )
    parser.add_argument(
        "--secret-name",
        help="Secrets Manager name; defaults to the provider-specific name.",
    )
    parser.add_argument(
        "--profile",
        default=os.environ.get("AWS_PROFILE"),
        help="AWS profile (defaults to AWS_PROFILE or the default chain).",
    )
    parser.add_argument("--region", default=os.environ.get("AWS_REGION"))
    parser.add_argument(
        "--outputs-file",
        type=Path,
        default=Path("cdk-outputs.json"),
    )
    parser.add_argument("--stack", help="Stack key in the CDK outputs file.")
    return parser.parse_args()


def _client_secret(environment_name: str) -> str:
    value = os.environ.get(environment_name)
    if value:
        return value
    if not sys.stdin.isatty():
        raise SystemExit(
            f"Set {environment_name} or run interactively to enter the secret."
        )
    value = getpass.getpass("OAuth client secret: ")
    if not value:
        raise SystemExit("OAuth client secret cannot be empty.")
    return value


def _secret_exists(client: SecretsManagerClient, secret_name: str) -> bool:
    try:
        client.describe_secret(SecretId=secret_name)
    except ClientError as exc:
        error = exc.response.get("Error", {})
        if error.get("Code") == "ResourceNotFoundException":
            return False
        raise
    return True


def _secret_payload(
    *,
    provider: str,
    client_id: str,
    client_secret: str,
    tenant_id: str | None,
) -> dict[str, str]:
    if not client_id:
        raise SystemExit("Pass --client-id or set SSO_CLIENT_ID.")
    if not tenant_id:
        raise SystemExit(
            "Pass --tenant-id or set MICROSOFT_TENANT_ID for Microsoft."
        )
    return {
        "tenant_id": tenant_id,
        "client_id": client_id,
        "client_secret": client_secret,
    }


def main() -> None:
    args = _arguments()
    provider = str(args.provider)
    secret_name = str(args.secret_name or SECRET_NAMES[provider]).strip()
    if not secret_name:
        raise SystemExit("--secret-name cannot be empty.")
    payload = _secret_payload(
        provider=provider,
        client_id=str(args.client_id or "").strip(),
        client_secret=_client_secret(args.client_secret_env),
        tenant_id=str(args.tenant_id or "").strip() or None,
    )

    context = load_stack_context(args.outputs_file, args.stack)
    session = create_session(
        profile=args.profile,
        region=args.region,
        outputs=context.outputs,
    )
    secrets = session.client("secretsmanager")
    secret_string = json.dumps(payload)
    if _secret_exists(secrets, secret_name):
        response = secrets.put_secret_value(
            SecretId=secret_name,
            SecretString=secret_string,
        )
        action = "Updated"
    else:
        response = secrets.create_secret(
            Name=secret_name,
            Description=(
                f"{provider.title()} OAuth client used by "
                "Blend Knowledge Cognito SSO"
            ),
            SecretString=secret_string,
        )
        action = "Created"

    cognito_domain = require_output(context, "CognitoDomain").rstrip("/")
    print(f"{action} {provider} SSO credentials in Secrets Manager.")
    print(f"Secret ARN: {response.get('ARN', 'unknown')}")
    print("Identity-provider authorized origin:")
    print(f"  {cognito_domain}")
    print("Identity-provider redirect URI:")
    print(f"  {cognito_domain}/oauth2/idpresponse")
    environment_name = "MICROSOFT_SSO"
    secret_environment_name = "MICROSOFT_SSO_SECRET_NAME"
    profile_prefix = f"AWS_PROFILE={args.profile} " if args.profile else ""
    print("Enable the provider on the next deployment:")
    print(
        f"  {profile_prefix}{environment_name}=1 "
        f"{secret_environment_name}={secret_name} ./scripts/deploy.sh"
    )


if __name__ == "__main__":
    main()
