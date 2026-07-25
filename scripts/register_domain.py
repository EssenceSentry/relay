#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import TypedDict, TypeGuard

import boto3
from _type_guards import is_string_keyed_dict
from botocore.exceptions import ClientError
from mypy_boto3_route53domains import Route53DomainsClient
from mypy_boto3_route53domains.literals import (
    ContactTypeType,
    CountryCodeType,
)
from mypy_boto3_route53domains.type_defs import (
    ContactDetailTypeDef,
    DomainPriceTypeDef,
    PriceWithCurrencyTypeDef,
)

_ROUTE53_DOMAINS_REGION = "us-east-1"
_DOMAIN_RE = re.compile(
    r"(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z]{2,63}"
)
_TERMINAL_OPERATION_STATUSES = {"SUCCESSFUL", "FAILED", "ERROR"}


class RegistrationContacts(TypedDict):
    AdminContact: ContactDetailTypeDef
    RegistrantContact: ContactDetailTypeDef
    TechContact: ContactDetailTypeDef
    BillingContact: ContactDetailTypeDef


def _session(profile: str | None) -> boto3.Session:
    return boto3.Session(profile_name=profile) if profile else boto3.Session()


def _normalize_domain(value: str) -> str:
    domain = value.strip().casefold().rstrip(".")
    if not _DOMAIN_RE.fullmatch(domain):
        raise SystemExit(
            "Only ordinary ASCII domain names are supported by this helper. "
            f"Invalid value: {value!r}"
        )
    return domain


def _is_contact_type(value: object) -> TypeGuard[ContactTypeType]:
    return isinstance(value, str) and value in {
        "ASSOCIATION",
        "COMPANY",
        "PERSON",
        "PUBLIC_BODY",
        "RESELLER",
    }


def _is_country_code(value: object) -> TypeGuard[CountryCodeType]:
    return (
        isinstance(value, str)
        and len(value) == 2
        and value.isascii()
        and value.isalpha()
        and value.isupper()
    )


def _required_contact_text(
    contact: dict[str, object],
    key: str,
) -> str:
    value = contact.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"Contact is missing string field {key}")
    return value.strip()


def _optional_contact_text(
    contact: dict[str, object],
    key: str,
) -> str | None:
    value = contact.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _contact_detail(value: object) -> ContactDetailTypeDef:
    if not is_string_keyed_dict(value):
        raise SystemExit("Contact details must be a JSON object")
    contact_type = value.get("ContactType")
    if not _is_contact_type(contact_type):
        raise SystemExit(
            "ContactType must be ASSOCIATION, COMPANY, PERSON, "
            "PUBLIC_BODY, or RESELLER"
        )
    country_code = value.get("CountryCode")
    if not _is_country_code(country_code):
        raise SystemExit("CountryCode must be a two-letter uppercase code")

    contact: ContactDetailTypeDef = {
        "FirstName": _required_contact_text(value, "FirstName"),
        "LastName": _required_contact_text(value, "LastName"),
        "ContactType": contact_type,
        "AddressLine1": _required_contact_text(value, "AddressLine1"),
        "City": _required_contact_text(value, "City"),
        "CountryCode": country_code,
        "ZipCode": _required_contact_text(value, "ZipCode"),
        "PhoneNumber": _required_contact_text(value, "PhoneNumber"),
        "Email": _required_contact_text(value, "Email"),
    }
    organization = _optional_contact_text(value, "OrganizationName")
    address_line_2 = _optional_contact_text(value, "AddressLine2")
    state = _optional_contact_text(value, "State")
    fax = _optional_contact_text(value, "Fax")
    if organization:
        contact["OrganizationName"] = organization
    if address_line_2:
        contact["AddressLine2"] = address_line_2
    if state:
        contact["State"] = state
    if fax:
        contact["Fax"] = fax
    return contact


def _read_contact_file(path: Path) -> RegistrationContacts:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Contact file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"Contact file is not valid JSON: {path}: {exc}"
        ) from exc

    if not is_string_keyed_dict(payload):
        raise SystemExit("The contact file must contain a JSON object")

    common = payload.get("Contact")
    if common is not None:
        contact = _contact_detail(common)
        return {
            "AdminContact": contact,
            "RegistrantContact": contact,
            "TechContact": contact,
            "BillingContact": contact,
        }
    return {
        "AdminContact": _contact_detail(payload.get("AdminContact")),
        "RegistrantContact": _contact_detail(payload.get("RegistrantContact")),
        "TechContact": _contact_detail(payload.get("TechContact")),
        "BillingContact": _contact_detail(payload.get("BillingContact")),
    }


def _price_for_domain(
    client: Route53DomainsClient,
    domain: str,
) -> DomainPriceTypeDef | None:
    labels = domain.split(".")
    for start in range(1, len(labels)):
        candidate = ".".join(labels[start:])
        response = client.list_prices(Tld=candidate, MaxItems=1)
        prices = response.get("Prices", [])
        for price in prices:
            if str(price.get("Name", "")).casefold() == candidate:
                return price
    return None


def _format_price(value: PriceWithCurrencyTypeDef | None) -> str:
    if not value:
        return "unknown"
    return f"{value['Price']} {value['Currency']}"


def _print_price(price: DomainPriceTypeDef | None) -> None:
    if price is None:
        print("Route 53 price: unavailable from ListPrices")
        return
    print(
        "Route 53 price: "
        f"registration={_format_price(price.get('RegistrationPrice'))}; "
        f"renewal={_format_price(price.get('RenewalPrice'))}"
    )


def _wait_for_operation(
    client: Route53DomainsClient,
    operation_id: str,
    timeout: int,
) -> None:
    deadline = time.monotonic() + timeout
    last_status: str | None = None
    while True:
        response = client.get_operation_detail(OperationId=operation_id)
        status = str(response.get("Status") or "UNKNOWN")
        if status != last_status:
            print(f"Registration operation status: {status}")
            last_status = status
        if status in _TERMINAL_OPERATION_STATUSES:
            message = str(response.get("Message") or "").strip()
            if message:
                print(f"Operation message: {message}")
            if status != "SUCCESSFUL":
                raise SystemExit(1)
            return
        if time.monotonic() >= deadline:
            raise SystemExit(
                "Timed out waiting for registration. The operation continues in AWS. "
                f"Operation ID: {operation_id}"
            )
        time.sleep(15)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Check and optionally purchase a Route 53 domain. Dry-run is the "
            "default; an exact --confirm-purchase value is required to incur a charge."
        )
    )
    parser.add_argument("domain", help="Domain to check or register")
    parser.add_argument(
        "--contact-file",
        type=Path,
        help="JSON contact details; required only for purchase",
    )
    parser.add_argument(
        "--confirm-purchase",
        metavar="DOMAIN",
        help="Must exactly equal the normalized domain to submit registration",
    )
    parser.add_argument(
        "--duration-years",
        type=int,
        default=1,
        choices=range(1, 11),
        metavar="1..10",
    )
    parser.add_argument(
        "--auto-renew",
        action="store_true",
        help="Enable automatic renewal (off by default for the prototype)",
    )
    parser.add_argument(
        "--no-privacy",
        action="store_true",
        help="Disable contact privacy protection",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Poll the asynchronous registration operation",
    )
    parser.add_argument(
        "--wait-timeout",
        type=int,
        default=1800,
        help="Maximum wait in seconds (default: 1800)",
    )
    parser.add_argument("--profile", help="AWS CLI profile name")
    return parser


def main() -> None:
    args = _parser().parse_args()
    domain = _normalize_domain(args.domain)
    session = _session(args.profile)
    client = session.client(
        "route53domains", region_name=_ROUTE53_DOMAINS_REGION
    )

    availability = str(
        client.check_domain_availability(DomainName=domain).get("Availability")
        or "UNKNOWN"
    )
    print(f"Domain: {domain}")
    print(f"Availability: {availability}")
    _print_price(_price_for_domain(client, domain))

    confirmed = (
        _normalize_domain(args.confirm_purchase)
        if args.confirm_purchase
        else None
    )
    if confirmed is None:
        print(
            "Dry run only. No purchase was submitted. To purchase, add "
            f"--contact-file PATH --confirm-purchase {domain}"
        )
        return
    if confirmed != domain:
        raise SystemExit(
            "--confirm-purchase must exactly match the normalized domain: "
            f"{domain}"
        )
    if availability != "AVAILABLE":
        raise SystemExit(
            f"Refusing to purchase because availability is {availability}"
        )
    if args.contact_file is None:
        raise SystemExit("--contact-file is required when purchasing a domain")

    contacts = _read_contact_file(args.contact_file)
    privacy = not args.no_privacy
    print(
        "Submitting a billable Route 53 domain registration. Domain registrations "
        "cannot normally be refunded when the wrong name is purchased."
    )
    try:
        response = client.register_domain(
            DomainName=domain,
            DurationInYears=args.duration_years,
            AutoRenew=args.auto_renew,
            AdminContact=contacts["AdminContact"],
            RegistrantContact=contacts["RegistrantContact"],
            TechContact=contacts["TechContact"],
            BillingContact=contacts["BillingContact"],
            PrivacyProtectAdminContact=privacy,
            PrivacyProtectRegistrantContact=privacy,
            PrivacyProtectTechContact=privacy,
            PrivacyProtectBillingContact=privacy,
        )
    except ClientError as exc:
        error = exc.response.get("Error", {})
        raise SystemExit(
            f"Route 53 rejected the registration: {error.get('Code')}: "
            f"{error.get('Message')}"
        ) from exc

    operation_id = str(response["OperationId"])
    print(f"Registration submitted. Operation ID: {operation_id}")
    print(
        "Route 53 creates the public hosted zone and assigns it to the registered "
        "domain after registration succeeds. Watch the registrant inbox for any "
        "required verification message."
    )
    if args.wait:
        _wait_for_operation(client, operation_id, args.wait_timeout)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130) from None
