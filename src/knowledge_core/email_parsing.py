from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses
from html.parser import HTMLParser
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class ParsedInboundEmail:
    sender: str
    subject: str
    reply_text: str


_TOKEN_RE_TEMPLATE = r"^kg-([A-Za-z0-9_-]{{16,}})@{domain}$"
_QUOTED_PATTERNS = (
    re.compile(r"\nOn .{0,700}?wrote:\s*\n", re.IGNORECASE | re.DOTALL),
    re.compile(
        r"\n-{2,}\s*Original Message\s*-{2,}\s*\n",
        re.IGNORECASE,
    ),
    re.compile(
        r"\nFrom:\s*.+\n(?:Sent|Date):\s*.+\nTo:\s*.+\nSubject:\s*.+",
        re.IGNORECASE,
    ),
)


def extract_reply_token(
    recipients: Iterable[str], reply_domain: str
) -> str | None:
    domain_pattern = re.escape(reply_domain.strip().casefold().rstrip("."))
    pattern = re.compile(
        _TOKEN_RE_TEMPLATE.format(domain=domain_pattern),
        re.IGNORECASE,
    )
    for _, address in getaddresses(list(recipients)):
        match = pattern.fullmatch(address.strip().casefold())
        if match:
            return match.group(1)
    return None


def parse_inbound_email(
    raw_message: bytes,
    *,
    max_answer_chars: int = 20_000,
) -> ParsedInboundEmail:
    message = BytesParser(policy=policy.default).parsebytes(raw_message)
    sender = _first_address(message.get_all("from", []))
    if not sender:
        raise ValueError("Incoming email has no usable From address")
    body = _extract_body(message)
    reply = strip_quoted_reply(body).strip()
    if not reply:
        raise ValueError("Incoming email did not contain a usable reply")
    if len(reply) > max_answer_chars:
        reply = reply[:max_answer_chars].rstrip()
    return ParsedInboundEmail(
        sender=sender.casefold(),
        subject=str(message.get("subject") or "").strip(),
        reply_text=reply,
    )


def strip_quoted_reply(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    cut_at = len(normalized)
    for pattern in _QUOTED_PATTERNS:
        match = pattern.search("\n" + normalized)
        if match:
            cut_at = min(cut_at, max(0, match.start() - 1))

    lines = normalized[:cut_at].splitlines()
    kept: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith(">"):
            break
        kept.append(line.rstrip())

    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept).strip()


def _first_address(values: Iterable[str]) -> str | None:
    for _, address in getaddresses(list(values)):
        normalized = address.strip()
        if normalized:
            return normalized
    return None


def _extract_body(message: EmailMessage) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            if part.is_multipart():
                continue
            disposition = str(part.get_content_disposition() or "")
            if disposition == "attachment":
                continue
            content_type = part.get_content_type()
            if content_type == "text/plain":
                plain_parts.append(_part_text(part))
            elif content_type == "text/html":
                html_parts.append(_part_text(part))
    else:
        content_type = message.get_content_type()
        if content_type == "text/html":
            html_parts.append(_part_text(message))
        else:
            plain_parts.append(_part_text(message))

    plain = "\n".join(part for part in plain_parts if part.strip()).strip()
    if plain:
        return plain
    html = "\n".join(part for part in html_parts if part.strip()).strip()
    if html:
        return _html_to_text(html)
    return ""


def _part_text(part: EmailMessage) -> str:
    try:
        content = part.get_content()
    except (LookupError, UnicodeError):
        payload = part.get_payload(decode=True)
        if isinstance(payload, bytes):
            return payload.decode("utf-8", errors="replace")
        return str(payload or "")
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    return str(content)


class _TextExtractor(HTMLParser):
    _BLOCK_TAGS: ClassVar[set[str]] = {
        "br",
        "div",
        "p",
        "li",
        "tr",
        "h1",
        "h2",
        "h3",
        "h4",
        "blockquote",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        del attrs
        if tag.casefold() in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _html_to_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    text = "".join(parser.parts)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()
