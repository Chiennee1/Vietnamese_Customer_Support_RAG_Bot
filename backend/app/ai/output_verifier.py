import re
from dataclasses import dataclass

from app.ai.rag.citations import Citation, CitationVerifier

SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{10,}\b", re.IGNORECASE),
    re.compile(r"\b(?:password|jwt_secret|api_key)\s*[:=]", re.IGNORECASE),
)
UNSUPPORTED_PROMISE_PATTERNS = (
    re.compile(
        r"\b(?:chắc chắn|đảm bảo|cam kết)\b.{0,60}"
        r"\b(?:hoàn tiền|đổi máy|thay máy|bồi thường|duyệt bảo hành)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:tôi|hệ thống)\s+đã\s+(?:duyệt|chấp thuận|phê duyệt)"
        r"\s+(?:hoàn tiền|đổi máy|bồi thường|bảo hành)\b",
        re.IGNORECASE,
    ),
)
INTERNAL_DISCLOSURE_PATTERNS = (
    re.compile(r"\bBEGIN_(?:TRUSTED_DATA|CONVERSATION_DATA)\b"),
    re.compile(r"\b(?:system_prompt|chain[- ]of[- ]thought|hidden prompt)\b", re.IGNORECASE),
)
PAYMENT_CARD_PATTERN = re.compile(r"(?<!\d)(?:\d[\s-]?){13,19}(?!\d)")


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
        if any(pattern.search(answer) for pattern in UNSUPPORTED_PROMISE_PATTERNS):
            errors.append("UNSUPPORTED_PROMISE")
        if any(pattern.search(answer) for pattern in INTERNAL_DISCLOSURE_PATTERNS):
            errors.append("INTERNAL_DISCLOSURE")
        if PAYMENT_CARD_PATTERN.search(answer):
            errors.append("PAYMENT_CARD_PATTERN")
        return OutputVerification(valid=not errors, errors=tuple(errors))
