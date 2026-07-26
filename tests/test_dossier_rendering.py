from __future__ import annotations

from pathlib import Path
from zipfile import is_zipfile

import pytest

from knowledge_core.dossier_rendering import (
    DossierValidationError,
    parse_dossier_markdown,
    render_dossier_files,
    render_latex_source,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "dossiers"


def _fixture_markdown(name: str = "chewy-nlp-seo.md") -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


def test_all_sample_dossiers_satisfy_the_rendering_contract() -> None:
    paths = sorted(_FIXTURES.glob("*.md"))

    assert len(paths) == 5
    for path in paths:
        dossier = parse_dossier_markdown(path.read_text(encoding="utf-8"))
        assert dossier.title
        assert dossier.descriptor
        assert dossier.section("Sources Used").bullets
        assert 1 <= len(dossier.section("Key Features").bullets) <= 8


def test_parser_rejects_a_missing_required_section() -> None:
    markdown = _fixture_markdown().replace(
        "## Business Value",
        "## Unsupported Heading",
    )

    with pytest.raises(
        DossierValidationError,
        match="Unsupported dossier section",
    ):
        parse_dossier_markdown(markdown)


def test_latex_preserves_content_and_escapes_special_characters() -> None:
    dossier = parse_dossier_markdown(_fixture_markdown())

    latex = render_latex_source(dossier)

    assert "\\usepackage{blenddossier}" in latex
    assert "Chewy NLP \\& SEO" in latex
    assert "\\metric{\\$8.3MM}{revenue}" in latex
    assert "\\$8.3MM revenue" in latex
    assert "chewy case study.pptx" in latex
    assert "\\begin{multicols}{2}" not in latex


def test_file_renderer_creates_editable_docx_and_compiled_pdf(
    tmp_path: Path,
) -> None:
    def fake_compiler(latex_path: Path) -> Path:
        pdf_path = latex_path.with_suffix(".pdf")
        pdf_path.write_bytes(b"%PDF-1.7\n% test dossier\n")
        return pdf_path

    rendered = render_dossier_files(
        _fixture_markdown(),
        tmp_path,
        pdf_compiler=fake_compiler,
    )

    assert rendered.markdown_path.is_file()
    assert rendered.latex_path.is_file()
    assert is_zipfile(rendered.docx_path)
    assert rendered.pdf_path.read_bytes().startswith(b"%PDF-")
    assert len(rendered.source_sha256) == 64
