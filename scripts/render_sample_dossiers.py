"""Render the five curated dossier fixtures for visual review."""

from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Final

from knowledge_core.dossier_rendering import (
    DossierCompilationError,
    PdfCompiler,
    render_dossier_files,
)

_ROOT: Final = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class Sample:
    fixture: str
    source: str


_SAMPLES: Final = (
    Sample(
        "chewy-nlp-seo.md",
        "chewy case study.pptx.md",
    ),
    Sample(
        "manufacturing-demand-forecasting.md",
        (
            "(LongForm)_180_Manufacturing_Data Science & Insights_"
            "Supply Chain_Demand Forecasting.pptx.md"
        ),
    ),
    Sample(
        "hospitality-loyalty-optimization.md",
        "Blend Hospitality Case Study - Loyalty Optimization.pptx.md",
    ),
    Sample(
        "aarp-content-recommendations.md",
        (
            "AARP Branded long form _201_Non-Profit_Data Science & "
            "Insights_Customer Experience_Content Recommendation Engine "
            "on Palantir Foundry.pptx.md"
        ),
    ),
    Sample(
        "asi-conversation-assistant.md",
        "ASI Conversation assistant.pptx.md",
    ),
)


def compile_with_tectonic(
    tectonic: Path,
    latex_path: Path,
) -> Path:
    pdf_path = latex_path.with_suffix(".pdf")
    completed = subprocess.run(
        [
            str(tectonic),
            "-X",
            "compile",
            "--outdir",
            str(latex_path.parent),
            "--outfmt",
            "pdf",
            "--print",
            "--untrusted",
            latex_path.name,
        ],
        cwd=latex_path.parent,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0 or not pdf_path.is_file():
        combined_output = "\n".join(
            part for part in (completed.stdout, completed.stderr) if part
        )
        tail = "\n".join(combined_output.splitlines()[-80:])
        raise DossierCompilationError(
            f"Tectonic failed for {latex_path.name}:\n{tail}"
        )
    return pdf_path


def render_samples(
    *,
    output_directory: Path,
    tectonic: Path | None,
) -> list[Path]:
    fixtures = _ROOT / "tests" / "fixtures" / "dossiers"
    source_directory = _ROOT / "data" / "downloaded_markdown"
    rendered_directories: list[Path] = []
    for sample in _SAMPLES:
        fixture = fixtures / sample.fixture
        source = source_directory / sample.source
        if not fixture.is_file():
            raise FileNotFoundError(f"Missing dossier fixture: {fixture}")
        if not source.is_file():
            raise FileNotFoundError(f"Missing source Markdown: {source}")
        destination = output_directory / fixture.stem
        compiler: PdfCompiler | None = (
            partial(compile_with_tectonic, tectonic)
            if tectonic is not None
            else None
        )
        render_dossier_files(
            fixture.read_text(encoding="utf-8"),
            destination,
            filename_stem=fixture.stem,
            pdf_compiler=compiler,
        )
        rendered_directories.append(destination)
    return rendered_directories


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=_ROOT / "output" / "dossiers",
    )
    parser.add_argument(
        "--tectonic",
        type=Path,
        help=(
            "Optional Tectonic binary for local previews. When omitted, "
            "the production XeLaTeX path is used."
        ),
    )
    args = parser.parse_args()
    directories = render_samples(
        output_directory=args.output.expanduser().resolve(),
        tectonic=(
            args.tectonic.expanduser().resolve()
            if args.tectonic is not None
            else None
        ),
    )
    for directory in directories:
        print(directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
