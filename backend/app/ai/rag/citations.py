import re
from dataclasses import dataclass
from uuid import UUID

from app.ai.router import normalize_for_routing

CITATION_PATTERN = re.compile(r"\[([A-Z]+-\d+)\]")
SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+|\n+")
CLAUSE_PATTERN = re.compile(r"[.!?;:\n]+")
CLAIM_CLAUSE_PATTERN = re.compile(
    r"[;:\n]+|(?<!\d),(?!\d)|"
    r"\s+(?:và|nhưng|song|tuy nhiên|hoặc|còn|hay|đồng thời|trong khi)\s+"
    r"(?=(?:"
    r"bạn|bị|cấm|có thể|cửa hàng|đơn|đổi|được|giao|hoàn|"
    r"hệ thống|khách|không|miễn|người|phải|sản phẩm|sẽ|"
    r"shop|thanh toán|thiết bị|từ chối|yêu cầu"
    r")\b)",
    re.IGNORECASE,
)
NEGATION_TOKENS = {"cam", "chang", "choi", "chua", "khong", "tru"}
NEGATION_BOUNDARIES = {"con", "hoac", "ma", "nhung", "song", "tuy", "va"}
LIVE_FACT_PREFIXES = (
    "dua tren du lieu he thong",
    "theo du lieu he thong",
)
POLICY_INDICATORS = (
    "bao hanh",
    "boi thuong",
    "cam ",
    "chi ",
    "chinh sach",
    "co the",
    "dieu kien",
    "doi may",
    "doi san pham",
    "doi tra",
    "duoc",
    "giao hang",
    "hoan tien",
    "hoan tra",
    "khong",
    "loai tru",
    "mien phi",
    "ngay",
    "phai",
    "phi ",
    "thanh toan",
    "thoi han",
    "tra hang",
    "tu choi",
    "van chuyen",
    "yeu cau",
)
LIVE_PREFIX_POLICY_INDICATORS = (
    "boi thuong",
    "cam ",
    "chinh sach",
    "co the",
    "dieu kien",
    "doi may",
    "doi san pham",
    "doi tra",
    "duoc",
    "hoan tien",
    "hoan tra",
    "loai tru",
    "mien phi",
    "phai",
    "thanh toan",
    "thoi han",
    "tra hang",
    "tu choi",
    "yeu cau",
)
NON_CLAIM_PREFIXES = (
    "ban can toi ho tro them",
    "ban co can toi ho tro them",
    "ban co cau hoi",
    "ban con can ho tro",
    "ban muon toi kiem tra",
    "cam on",
    "chuc ban",
    "hen gap lai",
    "neu ban can ho tro them",
    "rat tiec",
    "rat vui",
    "toi da kiem tra",
    "toi co the ho tro them",
    "toi hieu",
    "toi tim thay",
    "vui long lien he",
    "xin loi",
)
BUSINESS_TOPIC_INDICATORS = (
    "bao hanh",
    "boi thuong",
    "cam ",
    "chinh sach",
    "dieu kien",
    "doi may",
    "doi san pham",
    "doi tra",
    "hoan tien",
    "hoan tra",
    "loai tru",
    "mien phi",
    "thanh toan",
    "thoi han",
    "tra hang",
    "tu choi",
    "van chuyen",
    "yeu cau",
)
SUPPORT_STOPWORDS = {
    "bao",
    "cho",
    "chinh",
    "cua",
    "dieu",
    "doi",
    "duoc",
    "giao",
    "hanh",
    "hang",
    "khach",
    "khong",
    "kien",
    "la",
    "lieu",
    "mot",
    "nay",
    "nhan",
    "nhung",
    "quy",
    "sach",
    "theo",
    "thanh",
    "thi",
    "tin",
    "toan",
    "toi",
    "tra",
    "trong",
    "va",
    "voi",
}


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
    unsupported: tuple[str, ...] = ()


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
        uncited_policy_claim = citations_required and any(
            CITATION_PATTERN.search(sentence) is None and self._requires_policy_citation(sentence)
            for sentence in SENTENCE_PATTERN.split(answer)
        )
        missing = (
            ("REQUIRED_CITATION",)
            if citations_required and (not referenced or uncited_policy_claim)
            else ()
        )
        by_label = {citation.label: citation for citation in citations}
        unsupported_labels: set[str] = set()
        for sentence in SENTENCE_PATTERN.split(answer):
            labels = set(CITATION_PATTERN.findall(sentence)) & available
            unsupported_labels.update(
                self._unsupported_labels_for_claim(
                    claim=sentence,
                    labels=labels,
                    citations=by_label,
                )
            )
        unsupported = tuple(sorted(unsupported_labels))
        return CitationVerification(
            valid=not unknown and not missing and not unsupported,
            missing=missing,
            unknown=unknown,
            unsupported=unsupported,
        )

    @staticmethod
    def _unsupported_labels_for_claim(
        *,
        claim: str,
        labels: set[str],
        citations: dict[str, Citation],
    ) -> set[str]:
        if not labels:
            return set()
        cleaned_claim = CITATION_PATTERN.sub("", claim)
        clauses = [
            clause.strip()
            for clause in CLAIM_CLAUSE_PATTERN.split(cleaned_claim)
            if CitationVerifier._meaningful_terms(clause)
        ]
        if not clauses:
            return set(labels)
        support: dict[str, set[int]] = {
            label: {
                index
                for index, clause in enumerate(clauses)
                if CitationVerifier._supports_clause(
                    claim=clause,
                    citation=citations[label],
                )
            }
            for label in labels
        }
        unsupported = {label for label, clause_indexes in support.items() if not clause_indexes}
        covered_clauses = set().union(*support.values())
        if len(covered_clauses) != len(clauses):
            unsupported.update(labels)
        return unsupported

    @staticmethod
    def _supports_clause(
        *,
        claim: str,
        citation: Citation,
    ) -> bool:
        claim_terms = CitationVerifier._meaningful_terms(claim)
        source = " ".join(
            (
                citation.title,
                *citation.section_path,
                citation.excerpt,
            )
        )
        source_terms = CitationVerifier._meaningful_terms(source)
        overlap = claim_terms & source_terms
        if len(overlap) < 2:
            return False
        if len(overlap) / max(1, len(claim_terms)) < 0.7:
            return False
        claim_polarities = CitationVerifier._term_polarities(claim, overlap)
        source_polarities = CitationVerifier._term_polarities(source, overlap)
        if any(
            claim_polarities.get(term, set()).isdisjoint(source_polarities.get(term, set()))
            for term in overlap
        ):
            return False
        claim_numbers = set(re.findall(r"\b\d+(?:[.,]\d+)?\b", claim))
        source_numbers = set(re.findall(r"\b\d+(?:[.,]\d+)?\b", source))
        return claim_numbers <= source_numbers

    @staticmethod
    def _requires_policy_citation(sentence: str) -> bool:
        normalized = normalize_for_routing(sentence).strip()
        if not normalized:
            return False
        padded = f"{normalized} "
        if any(normalized.startswith(prefix) for prefix in LIVE_FACT_PREFIXES):
            return any(indicator in padded for indicator in LIVE_PREFIX_POLICY_INDICATORS)
        if any(normalized.startswith(prefix) for prefix in NON_CLAIM_PREFIXES) and not any(
            indicator in padded for indicator in BUSINESS_TOPIC_INDICATORS
        ):
            return False
        if any(indicator in padded for indicator in POLICY_INDICATORS):
            return True
        return len(CitationVerifier._meaningful_terms(normalized)) >= 2

    @staticmethod
    def _term_polarities(value: str, terms: set[str]) -> dict[str, set[bool]]:
        polarities: dict[str, set[bool]] = {term: set() for term in terms}
        for clause in CLAUSE_PATTERN.split(value):
            tokens = re.findall(r"[a-z0-9]+", normalize_for_routing(clause))
            for index, token in enumerate(tokens):
                if token not in terms:
                    continue
                window = tokens[max(0, index - 5) : index]
                last_boundary = max(
                    (
                        position
                        for position, candidate in enumerate(window)
                        if candidate in NEGATION_BOUNDARIES
                    ),
                    default=-1,
                )
                active_scope = window[last_boundary + 1 :]
                negated = any(
                    candidate in NEGATION_TOKENS
                    and (
                        offset + 1 >= len(active_scope)
                        or active_scope[offset + 1] not in {"chi", "nhung"}
                    )
                    for offset, candidate in enumerate(active_scope)
                )
                polarities[token].add(negated)
        return polarities

    @staticmethod
    def _meaningful_terms(value: str) -> set[str]:
        normalized = normalize_for_routing(value)
        return {
            token
            for token in re.findall(r"[a-z0-9]+", normalized)
            if len(token) >= 3 and token not in SUPPORT_STOPWORDS
        }
