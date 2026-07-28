from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_relay_story_assets_are_complete_and_linked() -> None:
    landing = (FRONTEND / "index.html").read_text(encoding="utf-8")
    demo = (FRONTEND / "demo.html").read_text(encoding="utf-8")
    landing_styles = (FRONTEND / "styles.css").read_text(encoding="utf-8")
    demo_styles = (FRONTEND / "demo.css").read_text(encoding="utf-8")
    script = (FRONTEND / "demo.js").read_text(encoding="utf-8")

    assert 'href="demo.html"' in landing
    assert 'src="demo.html?embed=1"' in landing
    assert 'title="Interactive Relay product story"' in landing
    assert 'src="demo.js"' in demo
    assert 'href="demo.css"' in demo
    assert 'classList.add("embedded-demo")' in demo
    assert ".embedded-demo .replay-frame" in demo_styles
    assert "agustin.sellanes@blend365.com" in script
    assert "essence.sentry@gmail.com" not in demo
    assert "essence.sentry@gmail.com" not in script
    assert 'id="mailbox-button"' not in demo
    assert "Evidence drawer" not in demo

    for shared_color in ("#17242b", "#e7603b", "#247c74", "#faf8f3"):
        assert shared_color in landing_styles
        assert shared_color in demo_styles

    for retired_landing_color in ("#102b38", "#eaf6f9", "#079bc4", "#075f7e"):
        assert retired_landing_color not in landing_styles

    for relative_path in (
        "demo.css",
        "demo.js",
        "demo-assets/avatar-seeker.png",
        "demo-assets/avatar-expert.png",
        "demo-assets/question-email.html",
        "demo-assets/follow-up-email.html",
        "demo-assets/agentic-knowledge-platform.html",
        "demo-assets/og-relay-story.png",
        "demo-assets/dossier-docx-first-page.png",
        "demo-assets/dossier-pdf-first-page.png",
    ):
        assert (FRONTEND / relative_path).is_file()


def test_relay_story_preserves_both_answer_channels_and_email_html() -> None:
    script = (FRONTEND / "demo.js").read_text(encoding="utf-8")
    question_email = (
        FRONTEND / "demo-assets" / "question-email.html"
    ).read_text(encoding="utf-8")
    follow_up_email = (
        FRONTEND / "demo-assets" / "follow-up-email.html"
    ).read_text(encoding="utf-8")

    assert "Answer through the connected agent" in script
    assert "Complete the answer in Outlook" in script
    assert "Sent by email" in script
    assert "October 15, 2026" in script
    assert "Use the relay plugin." in script
    assert (
        "looking for an offering that addresses fragmented institutional"
        in script
    )
    assert "Give me a download link for the original document." in script
    assert 'data-action="open-source"' in script
    assert 'data-action="open-dossier-docx"' in script
    assert 'data-action="open-dossier-pdf"' in script
    assert '<details class="long-response">' in script
    assert "Show complete indexed response" in script
    assert "demo-assets/dossier-docx-first-page.png" in script
    assert "demo-assets/dossier-pdf-first-page.png" in script
    assert "demo-assets/executive-dossier.html" not in script
    assert not (
        FRONTEND / "Agentic-Knowledge-Platform-Internal-GTM-Dossier.docx"
    ).exists()
    assert not (
        FRONTEND / "Agentic-Knowledge-Platform-Internal-GTM-Dossier.pdf"
    ).exists()
    assert "View document" not in script
    assert "Your expertise is needed" in question_email
    assert "Reply directly to this email." in question_email
    assert "one follow-up detail is needed" in follow_up_email
    assert "do not need to repeat your previous answer." in follow_up_email
