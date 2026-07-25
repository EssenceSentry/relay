from __future__ import annotations

import io
import subprocess
import tempfile
from pathlib import Path

from knowledge_core.ids import safe_filename

_OFFICE_SUFFIXES = {".doc", ".docx", ".pptx"}
_PDF_SUFFIX = ".pdf"


class DocumentRenderingError(RuntimeError):
    pass


def split_pdf_pages(rendered_pdf: bytes) -> list[bytes]:
    if not rendered_pdf.startswith(b"%PDF-"):
        raise DocumentRenderingError(
            "rendered_pdf does not contain a valid PDF header"
        )

    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(rendered_pdf))
    pages: list[bytes] = []
    for source_page in reader.pages:
        writer = PdfWriter()
        writer.add_page(source_page)
        output = io.BytesIO()
        writer.write(output)
        page_pdf = output.getvalue()
        if not page_pdf.startswith(b"%PDF-"):
            raise DocumentRenderingError(
                "Failed to serialize one rendered PDF page"
            )
        pages.append(page_pdf)
    if not pages:
        raise DocumentRenderingError("The rendered PDF contains no pages")
    return pages


def render_document_as_pdf(
    data: bytes,
    filename: str,
    *,
    soffice_path: str = "soffice",
    timeout_seconds: int = 240,
) -> bytes:
    suffix = Path(filename).suffix.casefold()
    if suffix == _PDF_SUFFIX:
        if not data.startswith(b"%PDF-"):
            raise DocumentRenderingError(
                f"{filename!r} does not contain a valid PDF header"
            )
        return data
    if suffix not in _OFFICE_SUFFIXES:
        raise DocumentRenderingError(
            f"Print rendering is not supported for {suffix or '<none>'}"
        )

    with tempfile.TemporaryDirectory(
        prefix="blend-document-render-",
        dir="/tmp",
    ) as temporary_directory:
        root = Path(temporary_directory)
        input_path = root / safe_filename(filename)
        output_directory = root / "output"
        profile_directory = root / "libreoffice-profile"
        output_directory.mkdir()
        profile_directory.mkdir()
        input_path.write_bytes(data)

        result = subprocess.run(
            [
                soffice_path,
                f"-env:UserInstallation={profile_directory.as_uri()}",
                "--headless",
                "--nologo",
                "--nodefault",
                "--nolockcheck",
                "--nofirststartwizard",
                "--convert-to",
                "pdf",
                "--outdir",
                str(output_directory),
                str(input_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        rendered_files = sorted(output_directory.glob("*.pdf"))
        if result.returncode != 0 or len(rendered_files) != 1:
            diagnostics = "\n".join(
                part.strip()
                for part in (result.stdout, result.stderr)
                if part.strip()
            )
            raise DocumentRenderingError(
                "LibreOffice failed to render "
                f"{filename!r} as PDF (exit {result.returncode}): "
                f"{diagnostics[:2000] or 'no diagnostics'}"
            )

        rendered = rendered_files[0].read_bytes()
        if not rendered.startswith(b"%PDF-"):
            raise DocumentRenderingError(
                f"LibreOffice produced an invalid PDF for {filename!r}"
            )
        return rendered
