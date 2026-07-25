from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from knowledge_core.document_rendering import render_document_as_pdf
from knowledge_core.models import TextSection
from knowledge_core.openai_api import (
    DOCUMENT_ENHANCEMENT_INSTRUCTIONS,
    OpenAIService,
)
from knowledge_core.parsing import parse_document

DEFAULT_SAMPLE_ROOTS = (
    Path("text_extraction"),
    Path("text_extraction/pdf"),
    Path("text_extraction/docx"),
)
DOCUMENT_ENHANCEMENT_PROMPT_SHA256 = hashlib.sha256(
    DOCUMENT_ENHANCEMENT_INSTRUCTIONS.encode("utf-8")
).hexdigest()


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reprocess existing extraction samples with printed pages and "
            "deterministic text in one multimodal OpenAI request."
        )
    )
    parser.add_argument(
        "sample_roots",
        nargs="*",
        type=Path,
        default=list(DEFAULT_SAMPLE_ROOTS),
        help="Sample directories containing manifest.json files.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get(
            "DOCUMENT_PROCESSING_MODEL",
            "gpt-5.4-mini",
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing document.md and enhancement.json files.",
    )
    return parser.parse_args()


def _serialize_sections(sections: list[TextSection]) -> str:
    rendered: list[str] = []
    for section in sections:
        metadata = [
            value
            for value in (
                f"title={section.title}" if section.title else None,
                f"locator={section.locator}" if section.locator else None,
                (
                    f"page_number={section.page_number}"
                    if section.page_number is not None
                    else None
                ),
            )
            if value
        ]
        prefix = f"[{', '.join(metadata)}]\n" if metadata else ""
        rendered.append(f"{prefix}{section.text}")
    return "\n\n".join(rendered)


def _atomic_write_text(path: Path, content: str) -> None:
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(content, encoding="utf-8")
    temporary_path.replace(path)


def _enhancement_fields(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: metadata[key]
        for key in (
            "document_processing_model",
            "image_detail",
            "document_enhancement_prompt_sha256",
            "deterministic_section_count",
            "deterministic_text_character_count",
            "deterministic_extraction_error",
            "rendered_page_count",
            "rendered_pdf_bytes",
            "enhanced_markdown_character_count",
            "enhanced_markdown_sha256",
            "enhanced_markdown_path",
            "enhancement_metadata_path",
        )
    }


def _process_entry(
    *,
    entry: dict[str, Any],
    service: OpenAIService,
    model: str,
    force: bool,
) -> tuple[dict[str, Any], bool]:
    source = Path(str(entry["source_copy"]))
    extraction_directory = Path(str(entry["extraction_directory"]))
    document_path = extraction_directory / "document.md"
    metadata_path = extraction_directory / "enhancement.json"
    if not source.is_file():
        raise FileNotFoundError(f"Sample source is missing: {source}")
    if not extraction_directory.is_dir():
        raise FileNotFoundError(
            f"Sample extraction directory is missing: {extraction_directory}"
        )

    if document_path.exists() and metadata_path.exists() and not force:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if (
            metadata.get("document_processing_model") == model
            and metadata.get("image_detail") == "high"
            and metadata.get("document_enhancement_prompt_sha256")
            == DOCUMENT_ENHANCEMENT_PROMPT_SHA256
        ):
            return {**entry, **_enhancement_fields(metadata)}, False

    data = source.read_bytes()
    deterministic_error: str | None = None
    try:
        deterministic_sections = parse_document(data, source.name)
    except Exception as exc:
        deterministic_sections = []
        deterministic_error = f"{type(exc).__name__}: {exc}"
    deterministic_text = _serialize_sections(deterministic_sections)
    rendered_pdf = render_document_as_pdf(data, source.name)
    markdown = service.enhance_document_markdown(
        filename=source.name,
        rendered_pdf=rendered_pdf,
        extracted_text=deterministic_text,
    )
    metadata = {
        "source_filename": source.name,
        "document_processing_model": model,
        "image_detail": "high",
        "document_enhancement_prompt_sha256": (
            DOCUMENT_ENHANCEMENT_PROMPT_SHA256
        ),
        "deterministic_section_count": len(deterministic_sections),
        "deterministic_text_character_count": len(deterministic_text),
        "deterministic_extraction_error": deterministic_error,
        "rendered_page_count": len(PdfReader(BytesIO(rendered_pdf)).pages),
        "rendered_pdf_bytes": len(rendered_pdf),
        "enhanced_markdown_character_count": len(markdown),
        "enhanced_markdown_sha256": hashlib.sha256(
            markdown.encode("utf-8")
        ).hexdigest(),
        "enhanced_markdown_path": str(document_path),
        "enhancement_metadata_path": str(metadata_path),
    }
    _atomic_write_text(document_path, f"{markdown.rstrip()}\n")
    _atomic_write_text(
        metadata_path,
        f"{json.dumps(metadata, ensure_ascii=False, indent=2)}\n",
    )
    return {**entry, **_enhancement_fields(metadata)}, True


def _render_readme(manifest: dict[str, Any]) -> str:
    extension = str(manifest["extension"]).upper()
    rows = [
        f"# {extension} multimodal extraction sample",
        "",
        (
            f"Random seed: `{manifest['seed']}`. Population: "
            f"`{manifest['population_size']}` {extension} files. Sample: "
            f"`{manifest['sample_size']}` files."
        ),
        "",
        (
            f"Each document was sent to `{manifest['document_processing_model']}` "
            "as a high-detail print-rendered PDF together with its "
            "deterministically extracted text."
        ),
        "",
        "Each `extracted/NN_*` directory contains:",
        "",
        "- `content.txt`: the original deterministic extraction.",
        "- `sections.json`: the original structured deterministic sections.",
        "- `document.md`: the cleaned and visually enhanced Markdown.",
        "- `enhancement.json`: model, rendering, and output metrics.",
        "",
        (
            f"| # | {extension} | Deterministic sections | "
            "Deterministic chars | Rendered pages | Enhanced chars |"
        ),
        "|---:|---|---:|---:|---:|---:|",
    ]
    for index, raw_entry in enumerate(manifest["files"], start=1):
        entry = dict(raw_entry)
        filename = str(entry["source_filename"]).replace("|", "\\|")
        rows.append(
            f"| {index} | {filename} | "
            f"{entry['deterministic_section_count']} | "
            f"{entry['deterministic_text_character_count']} | "
            f"{entry['rendered_page_count']} | "
            f"{entry['enhanced_markdown_character_count']} |"
        )

    if extension == "PPTX":
        rows.extend(
            [
                "",
                "## Additional format samples",
                "",
                "- [PDF extraction sample](pdf/README.md)",
                "- [DOCX extraction sample](docx/README.md)",
            ]
        )
    return "\n".join(rows) + "\n"


def _infer_extension(manifest: dict[str, Any]) -> str:
    configured = str(manifest.get("extension") or "").strip().casefold()
    if configured:
        return configured
    files = list(manifest.get("files") or [])
    if not files:
        raise ValueError("Cannot infer an extension from an empty manifest")
    suffixes = {
        Path(str(entry["source_filename"])).suffix.casefold().lstrip(".")
        for entry in files
    }
    if len(suffixes) != 1:
        raise ValueError(
            f"Manifest contains multiple document extensions: {suffixes}"
        )
    return suffixes.pop()


def _process_manifest(
    *,
    root: Path,
    service: OpenAIService,
    model: str,
    force: bool,
) -> tuple[int, int]:
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Sample manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["extension"] = _infer_extension(manifest)
    enhanced_count = 0
    files: list[dict[str, Any]] = []
    source_entries = list(manifest.get("files") or [])
    for index, raw_entry in enumerate(source_entries, start=1):
        entry, enhanced = _process_entry(
            entry=dict(raw_entry),
            service=service,
            model=model,
            force=force,
        )
        files.append(entry)
        enhanced_count += int(enhanced)
        action = "enhanced" if enhanced else "reused"
        print(
            f"{manifest['extension'].upper()} {index}/{len(source_entries)}: "
            f"{action}; {entry['rendered_page_count']} pages; "
            f"{entry['enhanced_markdown_character_count']} Markdown chars",
            flush=True,
        )

    manifest["files"] = files
    manifest["document_processing_model"] = model
    manifest["image_detail"] = "high"
    manifest["document_enhancement_prompt_sha256"] = (
        DOCUMENT_ENHANCEMENT_PROMPT_SHA256
    )
    manifest["enhancement_completed_at"] = datetime.now(UTC).isoformat()
    _atomic_write_text(
        manifest_path,
        f"{json.dumps(manifest, ensure_ascii=False, indent=2)}\n",
    )
    _atomic_write_text(root / "README.md", _render_readme(manifest))
    return len(files), enhanced_count


def main() -> None:
    args = _arguments()
    api_key = os.environ.get("OPENAI_API_KEY", "")
    service = OpenAIService(
        api_key=api_key,
        embedding_model="text-embedding-3-large",
        embedding_dimensions=1536,
        document_model=args.model,
    )
    total_files = 0
    total_enhanced = 0
    for root in args.sample_roots:
        file_count, enhanced_count = _process_manifest(
            root=root,
            service=service,
            model=args.model,
            force=args.force,
        )
        total_files += file_count
        total_enhanced += enhanced_count
    print(
        f"Completed {total_files} sample documents: "
        f"{total_enhanced} newly enhanced",
        flush=True,
    )


if __name__ == "__main__":
    main()
