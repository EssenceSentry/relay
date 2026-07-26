from __future__ import annotations

from typing import Any

from knowledge_core.email_service import SesEmailService


class FakeSesV2Client:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def send_email(self, **kwargs: Any) -> dict[str, str]:
        self.calls.append(kwargs)
        return {"MessageId": f"message-{len(self.calls)}"}


def _question() -> dict[str, str]:
    return {
        "project_id": "prj_123",
        "project_name": "Snowflake modernization",
        "question_id": "gap_456",
        "question": "Who owned the production cutover?",
        "context": "Retrieval found the timeline but not the accountable owner.",
        "priority": "high",
        "assigned_expert_email": "expert@example.com",
        "reply_address": f"kg-{'a' * 48}@answers.example.com",
    }


def test_send_question_sets_reply_to_and_web_fallback() -> None:
    client = FakeSesV2Client()
    service = SesEmailService(
        region_name="us-east-1",
        from_address="questions@answers.example.com",
        application_base_url="https://app.example.com/",
        client=client,
    )

    result = service.send_question(_question())

    assert result.message_id == "message-1"
    call = client.calls[0]
    assert call["FromEmailAddress"] == "questions@answers.example.com"
    assert call["Destination"] == {"ToAddresses": ["expert@example.com"]}
    assert call["ReplyToAddresses"] == [f"kg-{'a' * 48}@answers.example.com"]
    assert call["Content"]["Simple"]["Subject"]["Data"].startswith("[Blend360]")
    text = call["Content"]["Simple"]["Body"]["Text"]["Data"]
    html = call["Content"]["Simple"]["Body"]["Html"]["Data"]
    assert "Reply directly with your answer" in text
    assert "supported project documents" in text
    assert "https://app.example.com/" in text
    assert "#answer=" not in text
    assert "question_id=" not in text
    assert "Connect your agent" in html
    assert "Blend360 Project Knowledge" in html
    assert "Reply directly to this email" in html


def test_send_follow_up_asks_only_for_missing_detail() -> None:
    client = FakeSesV2Client()
    service = SesEmailService(
        region_name="us-east-1",
        from_address="questions@answers.example.com",
        application_base_url="https://app.example.com",
        client=client,
    )

    service.send_follow_up(
        _question(),
        missing_details=["Which migration stages did Priya own?"],
        review_rationale="The response named the lead but not the scope.",
    )

    call = client.calls[0]
    text = call["Content"]["Simple"]["Body"]["Text"]["Data"]
    html = call["Content"]["Simple"]["Body"]["Html"]["Data"]
    assert "Which migration stages did Priya own?" in text
    assert "You do not need to repeat your previous answer" in text
    assert "Reply directly with only the missing detail" in html
    assert "private answer link" not in html
    assert call["ReplyToAddresses"][0].startswith("kg-")


def test_email_delivery_does_not_require_a_browser_answer_token() -> None:
    client = FakeSesV2Client()
    service = SesEmailService(
        region_name="us-east-1",
        from_address="questions@answers.example.com",
        application_base_url="https://app.example.com",
        client=client,
    )
    question = _question()
    question["reply_address"] = "questions@answers.example.com"

    service.send_question(question)

    text = client.calls[0]["Content"]["Simple"]["Body"]["Text"]["Data"]
    assert "#answer=" not in text
    assert "https://app.example.com/" in text
