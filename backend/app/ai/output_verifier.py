import re
from dataclasses import dataclass

from app.ai.rag.citations import Citation, CitationVerifier

SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{10,}\b", re.IGNORECASE),
    re.compile(r"\b(?:password|jwt_secret|api_key)\s*[:=]", re.IGNORECASE),
)


@dataclass(frozen=True, slots=True)
class OutputVerification:
    valid: bool
    errors: tuple[str, ...]


class OutputVerifier:
    def __init__(self) -> None:
        self.citations = CitationVerifier()

    def verify(
        self,
        *,
        answer: str,
        citations: list[Citation],
        policy_claims: bool,
    ) -> OutputVerification:
        errors: list[str] = []
        citation_check = self.citations.verify(
            answer,
            citations,
            citations_required=policy_claims,
        )
        if citation_check.missing:
            errors.append("CITATION_REQUIRED")
        if citation_check.unknown:
            errors.append("UNKNOWN_CITATION")
        if any(pattern.search(answer) for pattern in SECRET_PATTERNS):
            errors.append("SECRET_PATTERN")
        return OutputVerification(valid=not errors, errors=tuple(errors))

