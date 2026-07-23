import re
from dataclasses import dataclass
from typing import Protocol

import tiktoken

from app.ai.rag.normalizer import normalize_for_search, normalize_text

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


class WhitespaceTokenCounter:
    def count(self, text: str) -> int:
        return max(1, len(text.split()))


class TiktokenCounter:
    def __init__(self, encoding_name: str = "cl100k_base") -> None:
        self.encoding = tiktoken.get_encoding(encoding_name)

    def count(self, text: str) -> int:
        return max(1, len(self.encoding.encode(text)))


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    content: str
    content_normalized: str
    section_path: list[str]
    page: int | None
    token_count: int


@dataclass(frozen=True, slots=True)
class _Section:
    page: int | None
    path: list[str]
    lines: list[str]


class SectionAwareChunker:
    def __init__(
        self,
        *,
        target_tokens: int = 500,
        max_tokens: int = 700,
        overlap_tokens: int = 80,
        token_counter: TokenCounter | None = None,
    ) -> None:
        if not 0 <= overlap_tokens < max_tokens:
            raise ValueError("overlap_tokens must be smaller than max_tokens")
        if not 1 <= target_tokens <= max_tokens:
            raise ValueError("target_tokens must be between 1 and max_tokens")
        self.target_tokens = target_tokens
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self.token_counter = token_counter or WhitespaceTokenCounter()

    def chunk_pages(self, pages: list[tuple[int | None, str]]) -> list[ChunkDraft]:
        sections: list[_Section] = []
        headings: list[str] = []
        for page, raw_text in pages:
            current_lines: list[str] = []
            current_path = list(headings)
            for line in normalize_text(raw_text).splitlines():
                heading = HEADING_PATTERN.match(line)
                if heading:
                    if current_lines:
                        sections.append(_Section(page=page, path=current_path, lines=current_lines))
                        current_lines = []
                    level = len(heading.group(1))
                    title = heading.group(2).strip()
                    headings = headings[: level - 1]
                    headings.append(title)
                    current_path = list(headings)
                    continue
                if line.strip():
                    current_lines.append(line)
            if current_lines:
                sections.append(_Section(page=page, path=current_path, lines=current_lines))

        chunks: list[ChunkDraft] = []
        for section in sections:
            chunks.extend(self._chunk_section(section))
        return chunks

    def _chunk_section(self, section: _Section) -> list[ChunkDraft]:
        heading_prefix = "\n".join(f"# {title}" for title in section.path)
        body = "\n".join(section.lines)
        content = f"{heading_prefix}\n{body}".strip()
        if self.token_counter.count(content) <= self.max_tokens:
            return [self._draft(content, section)]

        words = body.split()
        drafts: list[ChunkDraft] = []
        start = 0
        while start < len(words):
            end = start + 1
            while end <= len(words):
                candidate = f"{heading_prefix}\n{' '.join(words[start:end])}".strip()
                if self.token_counter.count(candidate) > self.max_tokens:
                    end -= 1
                    break
                end += 1
            end = min(max(end, start + 1), len(words))
            segment = words[start:end]
            segment_content = f"{heading_prefix}\n{' '.join(segment)}".strip()
            drafts.append(self._draft(segment_content, section))
            if end >= len(words):
                break
            overlap_start = end
            while overlap_start > start:
                overlap = " ".join(words[overlap_start - 1 : end])
                if self.token_counter.count(overlap) > self.overlap_tokens:
                    break
                overlap_start -= 1
            start = overlap_start if overlap_start < end else end
        return drafts

    def _draft(self, content: str, section: _Section) -> ChunkDraft:
        return ChunkDraft(
            content=content,
            content_normalized=normalize_for_search(content),
            section_path=section.path,
            page=section.page,
            token_count=self.token_counter.count(content),
        )
