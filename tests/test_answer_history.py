from __future__ import annotations

from knowledge_core.answer_history import format_answer_history


def test_single_answer_is_returned_without_history_wrapper() -> None:
    result = format_answer_history(
        [
            {
                "answer_id": "ans_1",
                "answer": "Priya owned discovery and cutover.",
                "created_at": "2026-07-25T10:00:00Z",
            }
        ],
        current_answer_id="ans_1",
    )

    assert result == "Priya owned discovery and cutover."


def test_follow_up_review_receives_prior_and_current_answers() -> None:
    result = format_answer_history(
        [
            {
                "answer_id": "ans_1",
                "answer": "Priya led the migration.",
                "answer_source": "EMAIL",
                "answered_by": "expert@example.com",
                "created_at": "2026-07-25T10:00:00Z",
            },
            {
                "answer_id": "ans_2",
                "answer": "She owned discovery, planning, and production cutover.",
                "answer_source": "EMAIL",
                "answered_by": "expert@example.com",
                "created_at": "2026-07-25T10:05:00Z",
            },
        ],
        current_answer_id="ans_2",
    )

    assert "chronological and cumulative" in result
    assert "Priya led the migration." in result
    assert "production cutover" in result
    assert "Response 2 (current response)" in result


def test_answer_history_keeps_only_the_most_recent_window() -> None:
    answers = [
        {
            "answer_id": f"ans_{index}",
            "answer": f"reply {index}",
            "created_at": f"2026-07-25T10:0{index}:00Z",
        }
        for index in range(5)
    ]

    result = format_answer_history(
        answers,
        current_answer_id="ans_4",
        max_answers=3,
    )

    assert "reply 0" not in result
    assert "reply 1" not in result
    assert "reply 2" in result
    assert "reply 4" in result
