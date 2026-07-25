from __future__ import annotations

import asyncio
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

from app.mcp_server import build_mcp_server
from mcp.types import TextContent


class FakeRepository:
    def __init__(self) -> None:
        self.questions: dict[str, dict[str, Any]] = {}
        self.facts: dict[str, dict[str, Any]] = {}

    def get_question(
        self,
        *,
        project_id: str,
        question_id: str,
    ) -> dict[str, Any] | None:
        assert project_id == "prj_1"
        return self.questions.get(question_id)

    def get_verified_fact(
        self,
        *,
        project_id: str,
        fact_id: str,
    ) -> dict[str, Any] | None:
        assert project_id == "prj_1"
        return self.facts.get(fact_id)

    def put_verified_fact(
        self,
        *,
        project_id: str,
        fact_id: str,
        fact: Any,
        created_by: str,
    ) -> dict[str, Any]:
        item = {
            "project_id": project_id,
            "fact_id": fact_id,
            "name": fact.name,
            "value": fact.value,
            "provenance": fact.provenance,
            "created_by": created_by,
        }
        self.facts[fact_id] = item
        return item


class FakeQuestions:
    def __init__(self, repository: FakeRepository) -> None:
        self.repository = repository
        self.create_calls = 0

    def create_question(
        self,
        *,
        project_id: str,
        gap: Any,
        created_by: str,
        question_id: str,
    ) -> dict[str, Any]:
        self.create_calls += 1
        item = {
            "project_id": project_id,
            "project_name": "Project one",
            "question_id": question_id,
            "question": gap.question,
            "context": gap.context,
            "assigned_expert_email": gap.assigned_expert_email,
            "priority": gap.priority,
            "status": "OPEN",
            "notification_status": "SENT",
            "created_by": created_by,
        }
        self.repository.questions[question_id] = item
        return item


def _tool_map(server: Any) -> dict[str, Any]:
    return {tool.name: tool for tool in asyncio.run(server.list_tools())}


def _prompt_map(server: Any) -> dict[str, Any]:
    return {
        prompt.name: prompt for prompt in asyncio.run(server.list_prompts())
    }


def test_tool_catalog_has_safety_annotations_and_bounded_inputs() -> None:
    tools = _tool_map(build_mcp_server(object()))  # type: ignore[arg-type]

    assert len(tools) == 10
    assert tools["search_knowledge"].annotations.readOnlyHint is True
    assert tools["search_knowledge"].meta == {
        "securitySchemes": [{"type": "noauth"}]
    }
    assert tools["search_knowledge"].inputSchema["properties"]["top_k"] == {
        "default": 5,
        "description": (
            "Number of ranked results to return. Use 5 for focused lookup "
            "or 10-20 for broader dossier research."
        ),
        "maximum": 25,
        "minimum": 1,
        "title": "Top K",
        "type": "integer",
    }
    create = tools["create_knowledge_gap"]
    assert create.annotations.readOnlyHint is False
    assert create.annotations.destructiveHint is True
    assert create.annotations.idempotentHint is True
    assert create.annotations.openWorldHint is True
    assert "request_id" in create.inputSchema["required"]
    assert create.inputSchema["properties"]["priority"]["enum"] == [
        "low",
        "normal",
        "high",
    ]
    resend = tools["resend_knowledge_gap_email"]
    assert resend.annotations.idempotentHint is False
    assert resend.annotations.openWorldHint is True


def test_server_guides_document_uploads_to_the_web_application() -> None:
    container = SimpleNamespace(
        settings=SimpleNamespace(
            application_base_url="https://essencesentry.shop",
            mcp_public_base_url="https://fallback.example",
            max_upload_bytes=25 * 1024 * 1024,
        )
    )

    server = build_mcp_server(container)  # type: ignore[arg-type]

    assert server.website_url == "https://essencesentry.shop/"
    assert server.instructions is not None
    assert "This MCP cannot upload documents." in server.instructions
    assert "https://essencesentry.shop/" in server.instructions
    assert "document upload area" in server.instructions
    assert "25 MiB" in server.instructions
    assert "list_project_documents" in server.instructions


def test_server_guides_agents_through_evidence_first_tool_use() -> None:
    server = build_mcp_server(object())  # type: ignore[arg-type]
    tools = _tool_map(server)

    assert server.instructions is not None
    ordered_guidance = [
        "1. If the exact project_id is unknown, call list_projects",
        "2. Call search_knowledge with several focused queries",
        "3. Search results are previews, not complete evidence",
        "4. Answer only from retrieved document text and verified facts",
        "5. If multiple focused searches",
        "6. Before create_knowledge_gap or resend_knowledge_gap_email",
    ]
    positions = [server.instructions.index(text) for text in ordered_guidance]
    assert positions == sorted(positions)
    assert "valid range is 1-25" in server.instructions
    assert "Cite the document name and page, slide, or locator" in (
        server.instructions
    )
    assert "participant_sales_brief_generation prompt" in server.instructions

    assert "never invent a project ID" in tools["list_projects"].description
    assert "multiple focused queries" in tools["search_knowledge"].description
    assert "previews only" in tools["search_knowledge"].description
    assert "does not return document contents" in (
        tools["list_project_documents"].description
    )
    get_document_description = " ".join(
        tools["get_document_text"].description.split()
    )
    assert "before relying on a preview" in get_document_description
    download_description = " ".join(
        tools["get_document_download_url"].description.split()
    )
    assert "time-limited URL" in download_description
    assert "consolidated cleaned and enhanced Markdown" in download_description
    assert tools["get_document_download_url"].annotations.readOnlyHint is True
    assert "sends external email" in (tools["create_knowledge_gap"].description)
    assert "never promote an inference" in (
        tools["record_verified_fact"].description
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
    assert "Cite every material factual claim inline" in text
    assert "section alone does not satisfy the citation requirement" in text
    assert "Use `get_document_text` for every document" in text


def test_mcp_download_tool_returns_consolidated_markdown_url() -> None:
    class DownloadRepository:
        def get_document(
            self,
            *,
            project_id: str,
            document_id: str,
        ) -> dict[str, str]:
            assert project_id == "prj_1"
            assert document_id == "doc_1"
            return {
                "project_id": project_id,
                "document_id": document_id,
                "document_name": "Example.pptx",
                "s3_bucket": "documents",
                "s3_key": "uploads/prj_1/doc_1/Example.pptx",
                "enhanced_s3_key": ("extracted/prj_1/doc_1/document.md"),
            }

    class DownloadS3:
        def generate_presigned_url(
            self,
            ClientMethod: str,
            Params: Mapping[str, Any] | None = None,
            ExpiresIn: int = 3600,
            HttpMethod: str = "",
        ) -> str:
            del HttpMethod
            assert Params is not None
            assert ClientMethod == "get_object"
            assert Params["Key"].endswith("/document.md")
            assert ExpiresIn == 900
            return "https://download.example/document.md"

    server = build_mcp_server(
        SimpleNamespace(
            repository=DownloadRepository(),
            s3=DownloadS3(),
        )  # pyright: ignore[reportArgumentType]
    )

    _content, structured = asyncio.run(
        server.call_tool(
            "get_document_download_url",
            {
                "project_id": "prj_1",
                "document_id": "doc_1",
                "download_format": "markdown",
            },
        )
    )

    assert structured == {
        "project_id": "prj_1",
        "document_id": "doc_1",
        "document_name": "Example.pptx",
        "download_format": "markdown",
        "filename": "Example.pptx.md",
        "content_type": "text/markdown; charset=utf-8",
        "url": "https://download.example/document.md",
        "expires_in_seconds": 900,
    }


def test_write_request_ids_prevent_duplicate_records() -> None:
    repository = FakeRepository()
    questions = FakeQuestions(repository)
    container = SimpleNamespace(repository=repository, questions=questions)
    server = build_mcp_server(container)  # type: ignore[arg-type]
    gap_arguments = {
        "project_id": "prj_1",
        "question": "Who owned the launch?",
        "assigned_expert_email": "expert@example.com",
        "request_id": "gap-request-001",
    }
    fact_arguments = {
        "project_id": "prj_1",
        "name": "Launch owner",
        "value": "A. Expert",
        "provenance": "Confirmed by the project lead",
        "request_id": "fact-request-001",
    }

    asyncio.run(server.call_tool("create_knowledge_gap", gap_arguments))
    asyncio.run(server.call_tool("create_knowledge_gap", gap_arguments))
    asyncio.run(server.call_tool("record_verified_fact", fact_arguments))
    asyncio.run(server.call_tool("record_verified_fact", fact_arguments))

    assert questions.create_calls == 1
    assert len(repository.questions) == 1
    assert len(repository.facts) == 1
