from __future__ import annotations

import io
import subprocess
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from knowledge_core.document_rendering import (
    DocumentRenderingError,
    render_document_as_pdf,
    split_pdf_pages,
)


def test_pdf_rendering_preserves_original_bytes() -> None:
    data = b"%PDF-1.7\nsource"

    assert render_document_as_pdf(data, "source.pdf") == data


def test_pdf_rendering_rejects_invalid_pdf_bytes() -> None:
    with pytest.raises(DocumentRenderingError, match="valid PDF header"):
        render_document_as_pdf(b"not-pdf", "source.pdf")


def test_office_rendering_uses_isolated_libreoffice_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_command: list[str] = []

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        observed_command.extend(command)
        output_directory = Path(command[command.index("--outdir") + 1])
        input_path = Path(command[-1])
        (output_directory / f"{input_path.stem}.pdf").write_bytes(
            b"%PDF-1.7\nrendered"
        )
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="converted",
            stderr="",
        )

    monkeypatch.setattr(
        "knowledge_core.document_rendering.subprocess.run",
        fake_run,
    )

    rendered = render_document_as_pdf(
        b"office-document",
        "Case Study.docx",
    )

    assert rendered == b"%PDF-1.7\nrendered"
    assert observed_command[0] == "soffice"
    assert any(
        argument.startswith("-env:UserInstallation=file://")
        for argument in observed_command
    )
    assert "--headless" in observed_command
    assert observed_command[-1].endswith("Case-Study.docx")


def test_print_rendering_rejects_unsupported_formats() -> None:
    with pytest.raises(DocumentRenderingError, match="not supported"):
        render_document_as_pdf(b"text", "source.txt")


def test_split_pdf_pages_returns_one_pdf_per_page() -> None:
    writer = PdfWriter()
    for _ in range(4):
        writer.add_blank_page(width=612, height=792)
    rendered = io.BytesIO()
    writer.write(rendered)

    pages = split_pdf_pages(rendered.getvalue())

    assert len(pages) == 4
    assert all(page.startswith(b"%PDF-") for page in pages)
    assert all(len(PdfReader(io.BytesIO(page)).pages) == 1 for page in pages)
