from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from app.mcp_server import build_mcp_server
from mcp.types import TextContent

EXPECTED_V1_TOOLS = {
    "get_current_user",
    "search_user_directory",
    "list_my_notifications",
    "mark_notification_read",
    "list_my_collaboration_invitations",
    "decide_collaboration_invitation",
    "list_projects",
    "get_project",
    "create_project",
    "rename_project",
    "archive_project",
    "restore_project",
    "list_project_collaborators",
    "invite_project_collaborator",
    "remove_project_collaborator",
    "search_all_projects",
    "search_project_knowledge",
    "list_project_documents",
    "get_document",
    "get_document_text",
    "get_document_download_url",
    "render_project_dossier",
    "prepare_document_upload",
    "list_verified_facts",
    "create_verified_fact",
    "list_project_questions",
    "list_my_assigned_questions",
    "get_project_question",
    "list_question_answers",
    "create_project_question",
    "submit_question_answer",
    "review_question_answer",
    "resend_question_email",
}

OLD_TOOL_NAMES = {
    "search_knowledge",
    "create_knowledge_gap",
    "get_knowledge_gap",
    "resend_knowledge_gap_email",
    "record_verified_fact",
}

REQUEST_ID_TOOLS = {
    "create_project",
    "invite_project_collaborator",
    "prepare_document_upload",
    "render_project_dossier",
    "create_verified_fact",
    "create_project_question",
    "submit_question_answer",
    "review_question_answer",
    "resend_question_email",
}


def _tool_map(server: Any) -> dict[str, Any]:
    return {tool.name: tool for tool in asyncio.run(server.list_tools())}


def _prompt_map(server: Any) -> dict[str, Any]:
    return {
        prompt.name: prompt for prompt in asyncio.run(server.list_prompts())
    }


def test_v1_tool_catalog_is_complete_and_old_names_are_absent() -> None:
    tools = _tool_map(build_mcp_server(object()))  # type: ignore[arg-type]

    assert set(tools) == EXPECTED_V1_TOOLS
    assert OLD_TOOL_NAMES.isdisjoint(tools)
    assert all(
        tool.meta == {"securitySchemes": [{"type": "noauth"}]}
        for tool in tools.values()
    )
    for name in REQUEST_ID_TOOLS:
        assert "request_id" in tools[name].inputSchema["required"]


def test_tool_catalog_exposes_bounded_inputs_and_safety_annotations() -> None:
    tools = _tool_map(build_mcp_server(object()))  # type: ignore[arg-type]

    search = tools["search_project_knowledge"]
    assert search.annotations.readOnlyHint is True
    assert search.inputSchema["properties"]["top_k"]["minimum"] == 1
    assert search.inputSchema["properties"]["top_k"]["maximum"] == 25

    answer = tools["submit_question_answer"]
    assert answer.annotations.openWorldHint is True
    assert (
        answer.inputSchema["properties"]["supporting_document_ids"]["anyOf"][0][
            "maxItems"
        ]
        == 10
    )

    for name in {
        "archive_project",
        "remove_project_collaborator",
        "decide_collaboration_invitation",
        "review_question_answer",
    }:
        assert tools[name].annotations.destructiveHint is True

    for name in {
        "invite_project_collaborator",
        "prepare_document_upload",
        "create_project_question",
        "submit_question_answer",
        "review_question_answer",
        "resend_question_email",
    }:
        assert tools[name].annotations.openWorldHint is True

    render = tools["render_project_dossier"]
    assert render.annotations.openWorldHint is False
    assert render.annotations.destructiveHint is False
    assert render.inputSchema["properties"]["markdown"]["maxLength"] == 200_000

    assert tools["resend_question_email"].annotations.idempotentHint is True


def test_server_guides_agents_through_v1_workflows() -> None:
    container = SimpleNamespace(
        settings=SimpleNamespace(
            application_base_url="https://essencesentry.shop",
            mcp_public_base_url="https://fallback.example",
        )
    )
    server = build_mcp_server(container)  # type: ignore[arg-type]

    assert server.website_url == "https://essencesentry.shop/"
    assert server.instructions is not None
    for text in (
        "get_current_user",
        "search_user_directory",
        "search_all_projects",
        "list_projects",
        "search_project_knowledge",
        "get_document_text",
        "prepare_document_upload",
        "fallback_url",
        "Poll get_document until READY or FAILED",
        "explicit user confirmation",
        "create_project_question",
        "participant_sales_brief_generation prompt",
        "render_project_dossier",
        "author_display_name",
        "author_email",
        "list_project_collaborators",
        "email_verified",
    ):
        assert text in server.instructions
    assert (
        "Every authenticated reader may create and answer"
        in server.instructions
    )
    assert "can_edit=false" in server.instructions
    assert (
        "Do not list projects, enumerate project documents, and read everything"
        in server.instructions
    )
    assert "do not stop after reporting the gap" in server.instructions
    assert (
        "you MUST call get_project and list_project_collaborators"
        in server.instructions
    )
    assert "suggest the verified project author first" in server.instructions
    assert "offer to draft a question" in server.instructions
    assert (
        "do not call create_project_question until the user confirms"
        in server.instructions
    )


def test_sales_brief_prompt_requires_grounded_inline_citations() -> None:
    server = build_mcp_server(object())  # type: ignore[arg-type]
    prompts = _prompt_map(server)

    assert list(prompts) == ["participant_sales_brief_generation"]
    prompt = prompts["participant_sales_brief_generation"]
    assert [argument.name for argument in prompt.arguments] == [
        "project_id",
        "project_name",
        "additional_context",
    ]
    assert [argument.required for argument in prompt.arguments] == [
        True,
        True,
        False,
    ]

    rendered = asyncio.run(
        server.get_prompt(
            "participant_sales_brief_generation",
            {
                "project_id": "prj_1",
                "project_name": "Project One",
                "additional_context": "Emphasize supply-chain outcomes.",
            },
        )
    )
    content = rendered.messages[0].content
    assert isinstance(content, TextContent)
    text = content.text
    assert "Project ID: `prj_1`" in text
    assert "Project or case-study name: `Project One`" in text
    assert "Emphasize supply-chain outcomes." in text
    assert "`search_all_projects`" in text
    assert "`search_project_knowledge`" in text
    assert "Cite every material factual claim inline" in text
    assert "section alone does not satisfy the citation requirement" in text
    assert "Use `get_document_text` for the strongest" in text
    assert "Do not enumerate and read all project documents" in text
