from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def format_answer_history(
    answers: Sequence[dict[str, Any]],
    *,
    current_answer_id: str | None = None,
    max_answers: int = 6,
    max_chars_per_answer: int = 16_000,
) -> str:
    """Format cumulative expert replies for the sufficiency reviewer.

    Follow-up emails explicitly allow the expert to provide only the missing
    detail, so each review must see the earlier replies to the same question.
    The most recent replies are retained, and the current answer is forced into
    the window when concurrent submissions make ordering unusual.
    """
    if max_answers <= 0:
        raise ValueError("max_answers must be positive")
    if max_chars_per_answer <= 0:
        raise ValueError("max_chars_per_answer must be positive")

    cleaned = [
        answer for answer in answers if str(answer.get("answer") or "").strip()
    ]
    if not cleaned:
        raise ValueError("No usable expert answers were available for review")

    ordered = sorted(
        cleaned,
        key=lambda item: (
            str(item.get("created_at") or ""),
            str(item.get("answer_id") or ""),
        ),
    )
    selected = ordered[-max_answers:]

    if current_answer_id and not any(
        str(item.get("answer_id") or "") == current_answer_id
        for item in selected
    ):
        current = next(
            (
                item
                for item in ordered
                if str(item.get("answer_id") or "") == current_answer_id
            ),
            None,
        )
        if current is not None:
            selected = [*selected[-(max_answers - 1) :], current]
            selected = sorted(
                selected,
                key=lambda item: (
                    str(item.get("created_at") or ""),
                    str(item.get("answer_id") or ""),
                ),
            )

    if len(selected) == 1:
        return _truncate(
            str(selected[0]["answer"]).strip(), max_chars_per_answer
        )

    blocks = [
        "The following expert responses are chronological and cumulative. "
        "The newest response may contain only details requested in a follow-up."
    ]
    for index, answer in enumerate(selected, start=1):
        answer_id = str(answer.get("answer_id") or "")
        current_suffix = (
            " (current response)" if answer_id == current_answer_id else ""
        )
        source = str(answer.get("answer_source") or "unknown").casefold()
        timestamp = str(answer.get("created_at") or "unknown time")
        author = str(answer.get("answered_by") or "assigned expert")
        text = _truncate(str(answer["answer"]).strip(), max_chars_per_answer)
        blocks.append(
            f"Response {index}{current_suffix} — {timestamp}; {source}; {author}:\n{text}"
        )
    return "\n\n".join(blocks)


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 34].rstrip() + "\n[response truncated for review]"
