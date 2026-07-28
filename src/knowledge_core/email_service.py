from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any, Protocol, cast

import boto3


@dataclass(frozen=True, slots=True)
class EmailSendResult:
    message_id: str


class QuestionEmailSender(Protocol):
    def send_question(self, question: dict[str, Any]) -> EmailSendResult: ...

    def send_follow_up(
        self,
        question: dict[str, Any],
        *,
        missing_details: list[str],
        review_rationale: str,
    ) -> EmailSendResult: ...


class NotificationEmailSender(Protocol):
    def send_notification(
        self,
        notification: dict[str, Any],
    ) -> EmailSendResult: ...


class SesEmailService:
    def __init__(
        self,
        *,
        region_name: str,
        from_address: str,
        application_base_url: str,
        client: Any | None = None,
    ) -> None:
        self._from_address = from_address.strip()
        self._application_base_url = application_base_url.rstrip("/") + "/"
        self._client = client or boto3.client("sesv2", region_name=region_name)

    def send_question(self, question: dict[str, Any]) -> EmailSendResult:
        reply_address = _required(question, "reply_address")
        recipient = _required(question, "assigned_expert_email")
        project_name = _required(question, "project_name")
        question_text = _required(question, "question")
        context = str(question.get("context") or "").strip()
        priority = str(question.get("priority") or "normal").strip().title()
        application_url = self._application_base_url
        subject = (
            f"[Relay] Question for {_subject_fragment(project_name, limit=72)}"
        )

        text_lines = [
            "RELAY PROJECT KNOWLEDGE",
            "",
            "Your expertise is needed",
            f"Project: {project_name}",
            f"Priority: {priority}",
            "",
            "QUESTION",
            question_text,
        ]
        if context:
            text_lines.extend(["", "AGENT CONTEXT", context])
        text_lines.extend(
            [
                "",
                "Choose whichever response option is easiest:",
                (
                    "1. Reply directly with your answer. You may attach up to "
                    "10 supported project documents (25 MiB total)."
                ),
                (
                    "2. Connect your agent and ask it to list your assigned "
                    f"questions: {application_url}"
                ),
                "",
                "Your response is reviewed for completeness. When sufficient, it "
                "becomes reusable project knowledge for Blend360 teams.",
                "",
                "Thank you for sharing the detail that only a project expert can provide.",
            ]
        )

        html_context = ""
        if context:
            html_context = (
                '<div style="margin:20px 0 0;padding:16px 18px;border-left:3px '
                'solid #247c74;background:#f1f7f6;border-radius:4px 12px 12px 4px">'
                '<div style="font-size:12px;font-weight:700;color:#247c74;'
                'text-transform:uppercase;letter-spacing:.08em">Why this is being asked</div>'
                '<div style="margin-top:7px;white-space:pre-wrap;line-height:1.6;'
                f'color:#3f5158">{escape(context)}</div></div>'
            )
        html_body = _html_shell(
            title="Your expertise is needed",
            preheader=f"Help complete the project record for {project_name}.",
            body=(
                '<div style="margin-bottom:20px">'
                '<span style="display:inline-block;padding:6px 10px;border-radius:999px;'
                'background:#eef2f1;color:#536168;font-size:12px;font-weight:700">'
                f"{escape(project_name)}</span>"
                '<span style="display:inline-block;margin-left:7px;padding:6px 10px;'
                "border-radius:999px;background:#fff1ec;color:#ba4023;font-size:12px;"
                f'font-weight:700">{escape(priority)} priority</span></div>'
                '<p style="margin:0 0 10px;color:#536168;line-height:1.6">'
                "An agent found a gap in the available project material and identified "
                "you as the person who can help complete it.</p>"
                '<div style="margin:22px 0;padding:22px;border:1px solid #dce4e2;'
                'border-radius:14px;background:#fbfcfc">'
                '<div style="font-size:12px;font-weight:700;color:#247c74;'
                'text-transform:uppercase;letter-spacing:.08em">Question</div>'
                '<div style="margin-top:9px;font-size:20px;font-weight:700;'
                f'line-height:1.45;color:#17242b">{escape(question_text)}</div></div>'
                f"{html_context}"
                '<div style="margin:24px 0;padding:18px;border-radius:12px;'
                'background:#f1f7f6;color:#3f5158;line-height:1.6">'
                "<strong>Reply directly to this email.</strong> You may attach "
                "supporting PDF, Word, PowerPoint, text, Markdown, CSV, or JSON "
                "documents (up to 10 files and 25 MiB total).</div>"
                '<div style="margin:28px 0 18px;text-align:center">'
                f'<a href="{escape(application_url)}" style="display:inline-block;'
                "padding:14px 22px;border-radius:11px;background:#e7603b;color:#fff;"
                'font-weight:700;text-decoration:none">Connect your agent</a></div>'
                '<p style="margin:0;text-align:center;color:#536168;font-size:14px;'
                'line-height:1.55">Ask the connected agent to list your assigned '
                "questions, then submit the answer there.</p>"
                '<div style="margin-top:26px;padding-top:20px;border-top:1px solid '
                '#e2e8e6;color:#536168;font-size:13px;line-height:1.55">'
                "Your response is reviewed for completeness. Once accepted, it becomes "
                "reusable project knowledge for Blend360 teams.</div>"
            ),
        )
        return self._send(
            recipient=recipient,
            reply_address=reply_address,
            subject=subject,
            text_body="\n".join(text_lines),
            html_body=html_body,
        )

    def send_follow_up(
        self,
        question: dict[str, Any],
        *,
        missing_details: list[str],
        review_rationale: str,
    ) -> EmailSendResult:
        reply_address = _required(question, "reply_address")
        recipient = _required(question, "assigned_expert_email")
        project_name = _required(question, "project_name")
        question_text = _required(question, "question")
        application_url = self._application_base_url
        details = [
            detail.strip() for detail in missing_details if detail.strip()
        ]
        details_text = "\n".join(f"- {detail}" for detail in details)
        if not details_text:
            details_text = "- Please add the concrete detail needed to fully answer the question."
        subject = (
            f"[Relay] Follow-up for {_subject_fragment(project_name, limit=72)}"
        )

        text_body = "\n".join(
            [
                "RELAY PROJECT KNOWLEDGE",
                "",
                "Thank you — one follow-up detail is needed",
                f"Project: {project_name}",
                "",
                "WHAT WOULD COMPLETE THE ANSWER",
                details_text,
                "",
                "REVIEW NOTE",
                review_rationale,
                "",
                "Choose whichever response option is easiest:",
                (
                    "1. Reply with only the missing detail, optionally attaching "
                    "supporting project documents."
                ),
                (
                    "2. Connect your agent and ask it to list your assigned "
                    f"questions: {application_url}"
                ),
                "",
                "You do not need to repeat your previous answer.",
                "",
                "ORIGINAL QUESTION",
                question_text,
            ]
        )
        details_html = "".join(
            f"<li>{escape(detail)}</li>" for detail in details
        )
        if not details_html:
            details_html = "<li>Please add the concrete detail needed to fully answer the question.</li>"
        html_body = _html_shell(
            title="Thank you — one follow-up detail is needed",
            preheader=(
                f"Complete your answer for {project_name} without repeating it."
            ),
            body=(
                '<span style="display:inline-block;padding:6px 10px;border-radius:999px;'
                'background:#eef2f1;color:#536168;font-size:12px;font-weight:700">'
                f"{escape(project_name)}</span>"
                '<p style="margin:18px 0;color:#536168;line-height:1.6">'
                "Your response moved the project record forward. The review found a "
                "small amount of information still needed to make it reusable.</p>"
                '<div style="padding:18px 20px;border-radius:14px;background:#fff8ea;'
                'border:1px solid #f1ddb1">'
                '<div style="font-size:12px;font-weight:700;color:#8a5a12;'
                'text-transform:uppercase;letter-spacing:.08em">What would complete it</div>'
                f'<ul style="margin:10px 0 0;padding-left:20px;line-height:1.65">'
                f"{details_html}</ul></div>"
                '<div style="margin-top:16px;padding:15px 17px;border-radius:12px;'
                'background:#f3f6f5;color:#536168;line-height:1.55">'
                f"<strong>Review note:</strong> {escape(review_rationale)}</div>"
                '<div style="margin:24px 0;padding:18px;border-radius:12px;'
                'background:#f1f7f6;color:#3f5158;line-height:1.6">'
                "<strong>Reply directly with only the missing detail.</strong> "
                "You may attach supporting project documents and do not need to "
                "repeat your previous answer.</div>"
                '<div style="margin:28px 0 18px;text-align:center">'
                f'<a href="{escape(application_url)}" style="display:inline-block;'
                "padding:14px 22px;border-radius:11px;background:#e7603b;color:#fff;"
                'font-weight:700;text-decoration:none">Connect your agent</a></div>'
                '<div style="margin-top:26px;padding-top:20px;border-top:1px solid '
                '#e2e8e6;color:#536168;font-size:13px;line-height:1.55">'
                f"<strong>Original question</strong><br>{escape(question_text)}</div>"
            ),
        )
        return self._send(
            recipient=recipient,
            reply_address=reply_address,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )

    def send_notification(
        self,
        notification: dict[str, Any],
    ) -> EmailSendResult:
        recipient = _required(notification, "email")
        title = _required(notification, "title")
        message = _required(notification, "message")
        action_url = str(notification.get("action_url") or "").strip()
        data = cast(dict[str, Any], notification.get("data") or {})
        project_name = str(data.get("project_name") or "").strip()
        subject = f"[Relay] {_subject_fragment(title, limit=96)}"
        text_lines = ["RELAY PROJECT KNOWLEDGE", "", title, "", message]
        action_html = ""
        if action_url:
            text_lines.extend(["", f"Open Relay: {action_url}"])
            action_html = (
                '<div style="margin:28px 0 10px;text-align:center">'
                f'<a href="{escape(action_url)}" style="display:inline-block;'
                "padding:14px 22px;border-radius:11px;background:#e7603b;"
                'color:#fff;font-weight:700;text-decoration:none">'
                "Open Relay</a></div>"
            )
        project_badge = ""
        if project_name:
            project_badge = (
                '<span style="display:inline-block;margin-bottom:18px;'
                "padding:6px 10px;border-radius:999px;background:#eef2f1;"
                'color:#536168;font-size:12px;font-weight:700">'
                f"{escape(project_name)}</span>"
            )
        html_body = _html_shell(
            title=title,
            preheader=message,
            body=(
                f"{project_badge}"
                '<p style="margin:0;color:#536168;line-height:1.65;'
                f'font-size:16px">{escape(message)}</p>'
                f"{action_html}"
                '<div style="margin-top:26px;padding-top:20px;'
                "border-top:1px solid #e2e8e6;color:#718087;"
                'font-size:13px;line-height:1.55">'
                "This message was generated from Relay project activity."
                "</div>"
            ),
        )
        return self._send(
            recipient=recipient,
            reply_address=None,
            subject=subject,
            text_body="\n".join(text_lines),
            html_body=html_body,
        )

    def _send(
        self,
        *,
        recipient: str,
        reply_address: str | None,
        subject: str,
        text_body: str,
        html_body: str,
    ) -> EmailSendResult:
        request: dict[str, Any] = {
            "FromEmailAddress": self._from_address,
            "Destination": {"ToAddresses": [recipient]},
            "Content": {
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": text_body, "Charset": "UTF-8"},
                        "Html": {"Data": html_body, "Charset": "UTF-8"},
                    },
                }
            },
        }
        if reply_address:
            request["ReplyToAddresses"] = [reply_address]
        response = self._client.send_email(
            **request,
        )
        return EmailSendResult(message_id=str(response["MessageId"]))


def _required(item: dict[str, Any], key: str) -> str:
    value = str(item.get(key) or "").strip()
    if not value:
        raise ValueError(f"Question is missing required field {key!r}")
    return value


def _subject_fragment(value: str, limit: int = 110) -> str:
    one_line = " ".join(value.split())
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 1].rstrip() + "…"


def _html_shell(*, title: str, preheader: str, body: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)}</title></head>"
        '<body style="margin:0;padding:0;background:#eef2f1;'
        'font-family:Arial,Helvetica,sans-serif;color:#17242b">'
        '<div style="display:none;max-height:0;overflow:hidden;opacity:0;'
        f'color:transparent">{escape(preheader)}</div>'
        '<div style="max-width:680px;margin:0 auto;padding:34px 18px">'
        '<div style="padding:18px 24px;border-radius:18px 18px 0 0;'
        'background:#17242b;color:#fff">'
        '<span style="display:inline-block;width:34px;height:34px;'
        "margin-right:10px;border-radius:10px;background:#e7603b;"
        "font-family:Georgia,serif;font-size:21px;font-weight:700;"
        'line-height:34px;text-align:center;vertical-align:middle">R</span>'
        '<span style="font-size:15px;font-weight:700;vertical-align:middle">'
        "Relay</span></div>"
        '<div style="padding:34px 32px;background:#fff;border-radius:0 0 18px 18px;'
        'box-shadow:0 12px 36px rgba(23,36,43,.10)">'
        f'<h1 style="font-size:28px;line-height:1.22;margin:0 0 22px;'
        f'letter-spacing:-.02em;color:#17242b">{escape(title)}</h1>{body}'
        "</div>"
        '<div style="padding:18px 24px;color:#718087;font-size:12px;'
        'line-height:1.55;text-align:center">'
        "Sent by Relay. Reply to the original question "
        "email or answer through your connected agent.</div>"
        "</div></body></html>"
    )
