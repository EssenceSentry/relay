from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_frontend_splits_connection_and_contextual_upload_pages() -> None:
    landing = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    upload = (ROOT / "frontend" / "upload.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    for required in (
        'id="login-button"',
        'id="mcp-url"',
        'id="logout-button"',
    ):
        assert required in landing
    assert "Search trusted sources" in landing
    assert "Create cited briefs" in landing
    assert "Manage projects and knowledge gaps" in landing
    assert "A small interface, on purpose" in landing
    assert "Remote MCP" in landing
    assert "Relay supplies its current workflows" in landing
    assert 'href="assets/icon-mark.png"' in landing
    assert 'src="assets/icon-mark.png"' in landing
    assert 'href="assets/icon-mark.png"' in upload
    assert 'src="assets/icon-mark.png"' in upload
    assert 'id="download-plugin"' not in landing
    assert 'id="connection-info-modal"' not in landing
    assert "Download plugin" not in landing
    assert "Remote MCP URL" in landing
    for required in (
        'id="login-button"',
        'id="upload-panel"',
        'id="upload-project-context"',
        'id="file-input"',
        'id="logout-button"',
    ):
        assert required in upload
    assert 'id="project-select"' not in upload
    assert 'id="upload-panel"' not in landing
    for removed in (
        'id="project-list"',
        'id="search-form"',
        'id="question-form"',
        'id="notifications"',
        'id="answer-form"',
    ):
        assert removed not in landing
        assert removed not in upload
    assert "/api/public/question" not in script
    assert "/uploads/presign" in script
    assert 'xhr.open("POST", session.upload_url)' in script
    assert "session.upload_required" in script
    assert '"upload_project_id"' in script


def test_legacy_answer_link_only_shows_informational_notice() -> None:
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'id="legacy-answer-notice"' in html
    assert "Reply directly to the original email" in html
    assert 'window.location.hash.includes("answer=")' in script
