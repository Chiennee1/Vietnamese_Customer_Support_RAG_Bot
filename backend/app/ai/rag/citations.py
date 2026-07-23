import re
from dataclasses import dataclass
from uuid import UUID

CITATION_PATTERN = re.compile(r"\[([A-Z]+-\d+)\]")


@dataclass(frozen=True, slots=True)
class Citation:
    label: str
    document_id: UUID
    chunk_id: UUID
    title: str
    version: str
    section_path: list[str]
    page: int | None
    excerpt: str


@dataclass(frozen=True, slots=True)
class CitationVerification:
    valid: bool
    missing: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()


class CitationVerifier:
    def verify(
        self,
        answer: str,
        citations: list[Citation],
        *,
        citations_required: bool,
    ) -> CitationVerification:
        referenced = set(CITATION_PATTERN.findall(answer))
        available = {citation.label for citation in citations}
        unknown = tuple(sorted(referenced - available))
        missing = (
            ("REQUIRED_CITATION",)
            if citations_required and not referenced
            else ()
        )
        return CitationVerification(
            valid=not unknown and not missing,
            missing=missing,
            unknown=unknown,
        )
