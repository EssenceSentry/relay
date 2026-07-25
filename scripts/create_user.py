#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from _bootstrap_aws import (
    create_session,
    load_stack_context,
    require_output,
)
from botocore.exceptions import ClientError
from mypy_boto3_cognito_idp import CognitoIdentityProviderClient
from mypy_boto3_cognito_idp.type_defs import AttributeTypeTypeDef


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create or update a Cognito user with boto3. By default the "
            "invitation is suppressed and a permanent password is configured."
        )
    )
    parser.add_argument(
        "email",
        nargs="?",
        default=os.environ.get("EMAIL"),
        help="User email address (or set EMAIL).",
    )
    parser.add_argument(
        "--admin",
        action="store_true",
        default=os.environ.get("ADMIN") == "1",
        help="Add the user to the admins group.",
    )
    parser.add_argument(
        "--send-invitation",
        action="store_true",
        help=(
            "Let Cognito email a temporary password instead of configuring a "
            "permanent password locally."
        ),
    )
    parser.add_argument(
        "--password-env",
        default="PASSWORD",
        help="Environment variable containing the permanent password.",
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


def _password(args: argparse.Namespace) -> str | None:
    if args.send_invitation:
        return None
    password = os.environ.get(args.password_env)
    if password:
        return password
    if not sys.stdin.isatty():
        raise SystemExit(
            f"Set {args.password_env} or run interactively to enter a password."
        )
    first = getpass.getpass("Permanent password: ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise SystemExit("Passwords do not match.")
    if not first:
        raise SystemExit("Password cannot be empty.")
    return first


def _user_exists(
    client: CognitoIdentityProviderClient,
    pool_id: str,
    email: str,
) -> bool:
    try:
        client.admin_get_user(UserPoolId=pool_id, Username=email)
    except ClientError as exc:
        error = exc.response.get("Error", {})
        if error.get("Code") == "UserNotFoundException":
            return False
        raise
    return True


def main() -> None:
    args = _arguments()
    if not args.email:
        raise SystemExit("Pass an email address or set EMAIL.")
    email = args.email.strip().casefold()
    if "@" not in email:
        raise SystemExit(f"Invalid email address: {email!r}")
    password = _password(args)

    context = load_stack_context(args.outputs_file, args.stack)
    pool_id = require_output(context, "UserPoolId")
    session = create_session(
        profile=args.profile,
        region=args.region,
        outputs=context.outputs,
    )
    client = session.client("cognito-idp")
    exists = _user_exists(client, pool_id, email)

    attributes: list[AttributeTypeTypeDef] = [
        {"Name": "email", "Value": email},
        {"Name": "email_verified", "Value": "true"},
    ]
    if exists:
        client.admin_update_user_attributes(
            UserPoolId=pool_id,
            Username=email,
            UserAttributes=attributes,
        )
        if args.send_invitation:
            client.admin_create_user(
                UserPoolId=pool_id,
                Username=email,
                MessageAction="RESEND",
                DesiredDeliveryMediums=["EMAIL"],
            )
        action = "Updated"
    else:
        if args.send_invitation:
            client.admin_create_user(
                UserPoolId=pool_id,
                Username=email,
                UserAttributes=attributes,
                DesiredDeliveryMediums=["EMAIL"],
            )
        else:
            client.admin_create_user(
                UserPoolId=pool_id,
                Username=email,
                UserAttributes=attributes,
                MessageAction="SUPPRESS",
            )
        action = "Created"

    if password is not None:
        client.admin_set_user_password(
            UserPoolId=pool_id,
            Username=email,
            Password=password,
            Permanent=True,
        )
    if args.admin:
        client.admin_add_user_to_group(
            UserPoolId=pool_id,
            Username=email,
            GroupName="admins",
        )

    password_note = (
        "Cognito invitation requested"
        if args.send_invitation
        else "permanent password configured"
    )
    admin_note = ", admin enabled" if args.admin else ""
    print(f"{action} {email}: {password_note}{admin_note}.")


if __name__ == "__main__":
    main()
