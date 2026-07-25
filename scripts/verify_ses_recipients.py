#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError


def _session(profile: str | None) -> boto3.Session:
    return boto3.Session(profile_name=profile) if profile else boto3.Session()


def _identity(client: Any, email: str) -> dict[str, Any] | None:
    try:
        return client.get_email_identity(EmailIdentity=email)
    except client.exceptions.NotFoundException:
        return None


def _status(client: Any, email: str) -> tuple[str, bool]:
    response = _identity(client, email)
    if response is None:
        return "NOT_CREATED", False
    return (
        str(response.get("VerificationStatus") or "UNKNOWN"),
        bool(response.get("VerifiedForSendingStatus", False)),
    )


def _wait(client: Any, emails: list[str], timeout: int) -> None:
    deadline = time.monotonic() + timeout
    pending = set(emails)
    while pending:
        for email in list(pending):
            verification, can_send = _status(client, email)
            print(
                f"{email}: verification={verification}; "
                f"verified_for_sending={str(can_send).lower()}"
            )
            if can_send:
                pending.remove(email)
        if not pending:
            return
        if time.monotonic() >= deadline:
            raise SystemExit(
                "Timed out waiting for verification: "
                + ", ".join(sorted(pending))
            )
        time.sleep(10)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Create SES email identities for demo recipients. Each recipient must "
            "click the verification message while the SES account is in the sandbox."
        )
    )
    parser.add_argument("emails", nargs="+", help="Recipient email addresses")
    parser.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION", "us-east-1"),
    )
    parser.add_argument("--profile", help="AWS CLI profile name")
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--wait-timeout", type=int, default=900)
    args = parser.parse_args()

    emails = list(
        dict.fromkeys(email.strip().casefold() for email in args.emails)
    )
    if any("@" not in email for email in emails):
        raise SystemExit("Every recipient must be an email address")

    client = _session(args.profile).client("sesv2", region_name=args.region)
    for email in emails:
        existing = _identity(client, email)
        if existing is None:
            try:
                client.create_email_identity(EmailIdentity=email)
            except ClientError as exc:
                error = exc.response.get("Error", {})
                raise SystemExit(
                    f"Could not create SES identity for {email}: "
                    f"{error.get('Code')}: {error.get('Message')}"
                ) from exc
            print(f"Verification requested for {email}.")
        else:
            verification, can_send = _status(client, email)
            print(
                f"{email} already exists: verification={verification}; "
                f"verified_for_sending={str(can_send).lower()}"
            )

    print("Each recipient must open the SES verification email and approve it.")
    if args.wait:
        _wait(client, emails, args.wait_timeout)


if __name__ == "__main__":
    main()
