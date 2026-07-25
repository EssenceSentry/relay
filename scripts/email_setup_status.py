#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import boto3
from _type_guards import is_string_keyed_dict
from botocore.exceptions import ClientError


def _session(profile: str | None) -> boto3.Session:
    return boto3.Session(profile_name=profile) if profile else boto3.Session()


def _load_output(path: Path, key: str) -> str | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if not is_string_keyed_dict(payload) or len(payload) != 1:
        return None
    outputs = next(iter(payload.values()))
    if not is_string_keyed_dict(outputs):
        return None
    value = outputs.get(key)
    return str(value) if value is not None else None


def _find_zone_id(route53: Any, domain: str) -> str | None:
    response = route53.list_hosted_zones_by_name(DNSName=domain, MaxItems="1")
    zones = response.get("HostedZones", [])
    if not zones:
        return None
    zone = zones[0]
    if str(zone.get("Name", "")).rstrip(".").casefold() != domain.casefold():
        return None
    return str(zone["Id"]).split("/")[-1]


def _record_values(
    route53: Any, zone_id: str, domain: str, record_type: str
) -> list[str]:
    response = route53.list_resource_record_sets(
        HostedZoneId=zone_id,
        StartRecordName=domain,
        StartRecordType=record_type,
        MaxItems="1",
    )
    records = response.get("ResourceRecordSets", [])
    if not records:
        return []
    record = records[0]
    if (
        str(record.get("Name", "")).rstrip(".").casefold()
        != domain.rstrip(".").casefold()
        or record.get("Type") != record_type
    ):
        return []
    return [str(item["Value"]) for item in record.get("ResourceRecords", [])]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Show Route 53 and SES readiness for the reply-by-email workflow"
    )
    parser.add_argument("--domain", help="Email domain; defaults to CDK output")
    parser.add_argument(
        "--outputs-file",
        type=Path,
        default=Path("cdk-outputs.json"),
    )
    parser.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION", "us-east-1"),
    )
    parser.add_argument("--profile", help="AWS CLI profile name")
    args = parser.parse_args()

    domain = args.domain or _load_output(args.outputs_file, "EmailDomain")
    if not domain:
        raise SystemExit("Pass --domain or deploy with an EmailDomain output")
    domain = domain.strip().casefold().rstrip(".")

    session = _session(args.profile)
    sesv2 = session.client("sesv2", region_name=args.region)
    ses = session.client("ses", region_name=args.region)
    route53 = session.client("route53")

    print(f"Domain: {domain}")
    print(f"SES region: {args.region}")

    try:
        account = sesv2.get_account()
        print(
            "SES account: "
            f"production_access={str(account.get('ProductionAccessEnabled', False)).lower()}; "
            f"send_enabled={str(account.get('SendingEnabled', False)).lower()}"
        )
    except ClientError as exc:
        print(f"SES account status unavailable: {exc}")

    try:
        identity = sesv2.get_email_identity(EmailIdentity=domain)
        dkim = identity.get("DkimAttributes") or {}
        mail_from = identity.get("MailFromAttributes") or {}
        print(
            "SES domain identity: "
            f"verification={identity.get('VerificationStatus', 'UNKNOWN')}; "
            f"verified_for_sending={str(identity.get('VerifiedForSendingStatus', False)).lower()}; "
            f"dkim={dkim.get('Status', 'UNKNOWN')}; "
            f"mail_from={mail_from.get('MailFromDomainStatus', 'UNKNOWN')}"
        )
    except sesv2.exceptions.NotFoundException:
        print("SES domain identity: NOT_FOUND")

    try:
        active = ses.describe_active_receipt_rule_set().get("Metadata") or {}
        print(f"Active receipt rule set: {active.get('Name', 'NONE')}")
    except ClientError as exc:
        print(f"Active receipt rule set unavailable: {exc}")

    zone_id = _find_zone_id(route53, domain)
    if zone_id is None:
        print("Route 53 hosted zone: NOT_FOUND")
        return
    print(f"Route 53 hosted zone: {zone_id}")
    mx = _record_values(route53, zone_id, domain, "MX")
    dmarc = _record_values(route53, zone_id, f"_dmarc.{domain}", "TXT")
    print(f"Inbound MX: {', '.join(mx) if mx else 'NOT_FOUND'}")
    print(f"DMARC: {', '.join(dmarc) if dmarc else 'NOT_FOUND'}")


if __name__ == "__main__":
    main()
