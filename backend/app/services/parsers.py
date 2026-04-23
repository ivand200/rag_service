from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - optional outside PDF parsing environments
    PdfReader = None


@dataclass(slots=True)
class ParsedSegment:
    text: str
    page_number: int | None = None
    section_label: str | None = None


@dataclass(slots=True)
class ParsedDocument:
    segments: list[ParsedSegment]


def parse_document_bytes(filename: str, content: bytes) -> ParsedDocument:
    suffix = Path(filename).suffix.lower()
    if suffix == ".txt":
        text = content.decode("utf-8")
        return ParsedDocument(segments=[ParsedSegment(text=text)])
    if suffix == ".md":
        text = content.decode("utf-8")
        section_label = _first_markdown_heading(text)
        return ParsedDocument(segments=[ParsedSegment(text=text, section_label=section_label)])
    if suffix == ".pdf":
        return _parse_pdf(content)
    raise ValueError(f"Unsupported file type: {suffix}")


def _parse_pdf(content: bytes) -> ParsedDocument:
    if PdfReader is None:
        raise RuntimeError("PDF parsing requires the pypdf package")
    reader = PdfReader(BytesIO(content))
    segments: list[ParsedSegment] = []
    for index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            segments.append(
                ParsedSegment(text=text, page_number=index, section_label=f"Page {index}")
            )
    if not segments:
        raise ValueError("PDF does not contain extractable text")
    return ParsedDocument(segments=segments)


def _first_markdown_heading(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or None
    return None
