from __future__ import annotations

import argparse
import json
import random
import shutil
from pathlib import Path
from typing import TypedDict

from knowledge_core.models import TextSection
from knowledge_core.parsing import parse_document

DEFAULT_SEED = 20260725


class ExtractionEntry(TypedDict):
    source_filename: str
    source_copy: str
    extraction_directory: str
    section_count: int
    text_character_count: int


class ExtractionManifest(TypedDict):
    seed: int
    extension: str
    source_directory: str
    population_size: int
    sample_size: int
    files: list[ExtractionEntry]


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Copy a reproducible random document sample and extract its text."
        )
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("PIH - Dataset"),
        help="Directory containing the source documents.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("text_extraction"),
        help="New directory to create for the extraction sample.",
    )
    parser.add_argument(
        "--extension",
        default="pptx",
        help="File extension to sample, without the leading dot.",
    )
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    return parser.parse_args()


def _render_text(sections: list[TextSection]) -> str:
    parts: list[str] = []
    for section in sections:
        heading = section.title or section.locator or "Untitled section"
        metadata = [f"locator: {section.locator or ''}"]
        if section.page_number is not None:
            unit = (
                "slide"
                if (section.locator or "").startswith("slide ")
                else "page"
            )
            metadata.append(f"{unit}: {section.page_number}")
        parts.append(
            "\n".join(
                [
                    f"# {heading}",
                    f"[{', '.join(metadata)}]",
                    "",
                    section.text,
                ]
            )
        )
    return "\n\n".join(parts).strip() + "\n"


def _write_extraction(
    *,
    source: Path,
    source_copy: Path,
    extraction_dir: Path,
) -> ExtractionEntry:
    data = source.read_bytes()
    sections = parse_document(data, source.name)
    shutil.copy2(source, source_copy)
    extraction_dir.mkdir(parents=True)

    text = _render_text(sections)
    (extraction_dir / "content.txt").write_text(text, encoding="utf-8")
    (extraction_dir / "sections.json").write_text(
        json.dumps(
            [section.model_dump(exclude_none=True) for section in sections],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "source_filename": source.name,
        "source_copy": str(source_copy),
        "extraction_directory": str(extraction_dir),
        "section_count": len(sections),
        "text_character_count": sum(len(section.text) for section in sections),
    }


def _render_readme(manifest: ExtractionManifest) -> str:
    extension = str(manifest["extension"]).upper()
    content_description = {
        "DOC": "document body and text boxes",
        "DOCX": "paragraph, heading, and table text",
        "PDF": "page text",
        "PPTX": "slide text, tables, and speaker notes",
    }.get(extension, "structured document text")
    rows = [
        f"# {extension} text extraction sample",
        "",
        (
            f"Random seed: `{manifest['seed']}`. Population: "
            f"`{manifest['population_size']}` {extension} files. Sample: "
            f"`{manifest['sample_size']}` files."
        ),
        "",
        "Each `extracted/NN_*` directory contains:",
        "",
        f"- `content.txt`: {content_description}.",
        "- `sections.json`: structured text sections used by ingestion.",
        "",
        f"| # | {extension} | Sections | Text chars |",
        "|---:|---|---:|---:|",
    ]
    for index, entry in enumerate(manifest["files"], start=1):
        filename = str(entry["source_filename"]).replace("|", "\\|")
        rows.append(
            f"| {index} | {filename} | {entry['section_count']} | "
            f"{entry['text_character_count']} |"
        )
    return "\n".join(rows) + "\n"


def main() -> None:
    args = _arguments()
    if args.count <= 0:
        raise ValueError("--count must be positive")
    if args.output.exists():
        raise FileExistsError(f"Output directory already exists: {args.output}")

    extension = args.extension.strip().casefold().lstrip(".")
    if not extension or not extension.isalnum():
        raise ValueError("--extension must contain only letters and numbers")
    candidates = sorted(
        (
            path
            for path in args.source.iterdir()
            if path.is_file() and path.suffix.casefold() == f".{extension}"
        ),
        key=lambda path: path.name.casefold(),
    )
    if args.count > len(candidates):
        raise ValueError(
            f"Requested {args.count} files from a population of "
            f"{len(candidates)}"
        )
    selected = random.Random(args.seed).sample(candidates, args.count)

    source_dir = args.output / "source"
    extracted_dir = args.output / "extracted"
    source_dir.mkdir(parents=True)
    extracted_dir.mkdir()

    files: list[ExtractionEntry] = []
    for index, source in enumerate(selected, start=1):
        extraction_dir = extracted_dir / f"{index:02d}_{source.stem}"
        files.append(
            _write_extraction(
                source=source,
                source_copy=source_dir / source.name,
                extraction_dir=extraction_dir,
            )
        )

    manifest: ExtractionManifest = {
        "seed": args.seed,
        "extension": extension,
        "source_directory": str(args.source),
        "population_size": len(candidates),
        "sample_size": len(selected),
        "files": files,
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.output / "README.md").write_text(
        _render_readme(manifest),
        encoding="utf-8",
    )

    total_sections = sum(int(entry["section_count"]) for entry in files)
    print(
        f"Extracted {len(files)} {extension.upper()} files into {args.output}: "
        f"{total_sections} sections"
    )


if __name__ == "__main__":
    main()
