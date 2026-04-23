from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import Settings
from app.services.parsers import ParsedDocument

TOKEN_RE = re.compile(r"\S+")


@dataclass(slots=True)
class ChunkCandidate:
    chunk_index: int
    text: str
    snippet: str
    token_count: int
    page_number: int | None
    section_label: str | None


def chunk_document(parsed: ParsedDocument, settings: Settings) -> list[ChunkCandidate]:
    chunks: list[ChunkCandidate] = []
    chunk_index = 0

    for segment in parsed.segments:
        tokens = TOKEN_RE.findall(segment.text)
        if not tokens:
            continue

        step = settings.chunk_target_tokens - settings.chunk_overlap_tokens
        for start in range(0, len(tokens), step):
            window = tokens[start : start + settings.chunk_target_tokens]
            if not window:
                continue
            text = " ".join(window).strip()
            if not text:
                continue
            chunks.append(
                ChunkCandidate(
                    chunk_index=chunk_index,
                    text=text,
                    snippet=_snippet(text),
                    token_count=len(window),
                    page_number=segment.page_number,
                    section_label=segment.section_label,
                )
            )
            chunk_index += 1

    if not chunks:
        raise ValueError("Document did not produce any indexable chunks")
    return chunks


def _snippet(text: str, max_chars: int = 200) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."
