from __future__ import annotations

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
