from __future__ import annotations

from email.message import EmailMessage

import pytest

from knowledge_core.email_parsing import (
    extract_reply_token,
    parse_inbound_email,
    strip_quoted_reply,
)


def test_extract_reply_token_from_ses_recipient() -> None:
    token = "rmv7zqd2nkh8cl4x_3ab-pq9"

    assert (
        extract_reply_token(
            [f"Blend Knowledge <kg-{token}@answers.example.com>"],
            "answers.example.com",
        )
        == token
    )


def test_extract_reply_token_rejects_another_domain() -> None:
    assert (
        extract_reply_token(
            ["kg-rmv7zqd2nkh8cl4x_3ab-pq9@other.example.com"],
            "answers.example.com",
        )
        is None
    )


def test_parse_plain_text_reply_removes_quoted_thread() -> None:
    raw = (
        b"From: Priya Raman <priya@example.com>\r\n"
        b"To: kg-rmv7zqd2nkh8cl4x_3ab-pq9@answers.example.com\r\n"
        b"Subject: Re: Knowledge request\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        b"Priya led discovery, migration planning, and cutover.\r\n"
        b"\r\n"
        b"On Fri, Jul 24, 2026 at 10:00 AM Blend Knowledge wrote:\r\n"
        b"> Who led the migration?\r\n"
    )

    parsed = parse_inbound_email(raw)

    assert parsed.sender == "priya@example.com"
    assert parsed.subject == "Re: Knowledge request"
    assert (
        parsed.reply_text
        == "Priya led discovery, migration planning, and cutover."
    )


def test_parse_html_only_reply() -> None:
    raw = (
        b"From: expert@example.com\r\n"
        b"To: questions@example.com\r\n"
        b"Subject: Re: Question\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n"
        b"\r\n"
        b"<html><body><p>The pilot covered five business units.</p>"
        b"<p>It completed in March 2026.</p></body></html>"
    )

    parsed = parse_inbound_email(raw)

    assert parsed.reply_text == (
        "The pilot covered five business units.\nIt completed in March 2026."
    )


def test_strip_outlook_original_message() -> None:
    body = (
        "The owner was the Data Platforms practice.\n\n"
        "-----Original Message-----\n"
        "From: Knowledge Bot <questions@example.com>\n"
        "Sent: Friday, July 24, 2026 10:00 AM\n"
        "To: Expert <expert@example.com>\n"
        "Subject: Knowledge request"
    )

    assert (
        strip_quoted_reply(body) == "The owner was the Data Platforms practice."
    )


def _message_with_headers() -> EmailMessage:
    message = EmailMessage()
    message["From"] = "Expert <expert@blend360.com>"
    message["To"] = "kg-example-token-123@answers.example.com"
    message["Subject"] = "Re: Project question"
    return message


def test_parse_attachment_only_reply_accepts_supported_document() -> None:
    message = _message_with_headers()
    message.add_attachment(
        b"%PDF-1.7 project evidence",
        maintype="application",
        subtype="pdf",
        filename="Evidence.PDF",
    )

    parsed = parse_inbound_email(message.as_bytes())

    assert parsed.reply_text == ""
    assert len(parsed.attachments) == 1
    attachment = parsed.attachments[0]
    assert attachment.filename == "Evidence.PDF"
    assert attachment.content_type == "application/pdf"
    assert attachment.size_bytes == len(b"%PDF-1.7 project evidence")
    assert len(attachment.sha256) == 64
    assert parsed.attachment_errors == ()


def test_parse_ignores_inline_signature_image() -> None:
    message = _message_with_headers()
    message.set_content("The accountable lead was Priya Shah.")
    message.add_attachment(
        b"logo bytes",
        maintype="image",
        subtype="png",
        filename="signature-logo.png",
        disposition="inline",
    )
    message.add_attachment(
        b"delivery details",
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename="Delivery.docx",
    )

    parsed = parse_inbound_email(message.as_bytes())

    assert [item.filename for item in parsed.attachments] == ["Delivery.docx"]
    assert parsed.attachment_errors == ()


def test_parse_reports_unsupported_and_oversized_attachments() -> None:
    message = _message_with_headers()
    message.set_content("See the supporting material.")
    message.add_attachment(
        b"binary",
        maintype="application",
        subtype="octet-stream",
        filename="archive.zip",
    )
    message.add_attachment(
        b"123456",
        maintype="application",
        subtype="pdf",
        filename="too-large.pdf",
    )

    parsed = parse_inbound_email(
        message.as_bytes(),
        max_total_attachment_bytes=5,
    )

    assert parsed.attachments == ()
    assert "unsupported file type .zip" in parsed.attachment_errors[0]
    assert "exceed the 5 byte total limit" in parsed.attachment_errors[1]


def test_parse_enforces_attachment_count_but_keeps_usable_files() -> None:
    message = _message_with_headers()
    message.set_content("Two documents are attached.")
    for name in ("one.pdf", "two.pdf"):
        message.add_attachment(
            name.encode(),
            maintype="application",
            subtype="pdf",
            filename=name,
        )

    parsed = parse_inbound_email(
        message.as_bytes(),
        max_attachment_count=1,
    )

    assert [item.filename for item in parsed.attachments] == ["one.pdf"]
    assert "more than 1 attachments" in parsed.attachment_errors[0]


def test_parse_rejects_reply_with_no_text_or_supported_attachment() -> None:
    message = _message_with_headers()
    message.add_attachment(
        b"binary",
        maintype="application",
        subtype="zip",
        filename="archive.zip",
    )

    with pytest.raises(ValueError, match="usable reply text"):
        parse_inbound_email(message.as_bytes())
