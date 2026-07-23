from dataclasses import replace
from uuid import uuid4

import pytest

from app.ai.output_verifier import OutputVerifier
from app.ai.rag.citations import Citation


def citation() -> Citation:
    return Citation(
        label="KB-1",
        document_id=uuid4(),
        chunk_id=uuid4(),
        title="Chính sách",
        version="1.0",
        section_path=["Điều kiện"],
        page=2,
        excerpt="Sản phẩm cần giữ nguyên số serial để được tiếp nhận kiểm tra.",
    )


def test_policy_answer_requires_known_citation_and_rejects_secrets() -> None:
    verifier = OutputVerifier()

    valid = verifier.verify(
        answer="Sản phẩm cần giữ nguyên số serial để được tiếp nhận kiểm tra [KB-1].",
        citations=[citation()],
        policy_claims=True,
    )
    missing = verifier.verify(
        answer="Sản phẩm cần giữ nguyên số serial để được tiếp nhận kiểm tra.",
        citations=[citation()],
        policy_claims=True,
    )
    secret = verifier.verify(
        answer="API key: sk-demo-secret [KB-1].",
        citations=[citation()],
        policy_claims=True,
    )

    assert valid.valid
    assert not missing.valid
    assert "CITATION_REQUIRED" in missing.errors
    assert not secret.valid
    assert "SECRET_PATTERN" in secret.errors


def test_output_verifier_rejects_promises_internal_markers_and_card_numbers() -> None:
    verifier = OutputVerifier()

    promise = verifier.verify(
        answer="Tôi đảm bảo bạn sẽ được hoàn tiền.",
        citations=[],
        policy_claims=False,
    )
    internal = verifier.verify(
        answer="BEGIN_TRUSTED_DATA chứa dữ liệu nội bộ.",
        citations=[],
        policy_claims=False,
    )
    card = verifier.verify(
        answer="Số thẻ là 4111 1111 1111 1111.",
        citations=[],
        policy_claims=False,
    )

    assert "UNSUPPORTED_PROMISE" in promise.errors
    assert "INTERNAL_DISCLOSURE" in internal.errors
    assert "PAYMENT_CARD_PATTERN" in card.errors


def test_citation_must_have_lexical_support_for_the_attached_claim() -> None:
    result = OutputVerifier().verify(
        answer="Cửa hàng chắc chắn tặng một xe máy [KB-1].",
        citations=[citation()],
        policy_claims=True,
    )

    assert not result.valid
    assert "UNSUPPORTED_CITATION" in result.errors


def test_citation_rejects_conflicting_numbers_despite_topic_overlap() -> None:
    source = citation()
    source = replace(
        source,
        excerpt="Yêu cầu hoàn tiền phải gửi trong 7 ngày từ khi nhận hàng.",
    )

    result = OutputVerifier().verify(
        answer="Yêu cầu hoàn tiền được gửi trong 90 ngày từ khi nhận hàng [KB-1].",
        citations=[source],
        policy_claims=True,
    )

    assert not result.valid
    assert "UNSUPPORTED_CITATION" in result.errors


def test_citation_rejects_opposite_negation_polarity() -> None:
    source = replace(
        citation(),
        excerpt="Sản phẩm không được hoàn tiền nếu đã mở hộp.",
    )

    result = OutputVerifier().verify(
        answer="Sản phẩm được hoàn tiền nếu đã mở hộp [KB-1].",
        citations=[source],
        policy_claims=True,
    )

    assert not result.valid
    assert "UNSUPPORTED_CITATION" in result.errors


def test_citation_polarity_is_scoped_to_the_supported_clause() -> None:
    source = replace(
        citation(),
        excerpt="Cửa hàng không hoàn tiền, nhưng hỗ trợ đổi sản phẩm lỗi.",
    )

    result = OutputVerifier().verify(
        answer="Cửa hàng hỗ trợ đổi sản phẩm lỗi [KB-1].",
        citations=[source],
        policy_claims=True,
    )

    assert result.valid


def test_every_policy_sentence_requires_its_own_citation() -> None:
    result = OutputVerifier().verify(
        answer=("Khách được hoàn tiền sau 90 ngày. Sản phẩm cần giữ nguyên số serial [KB-1]."),
        citations=[citation()],
        policy_claims=True,
    )

    assert not result.valid
    assert "CITATION_REQUIRED" in result.errors


@pytest.mark.parametrize(
    "excerpt",
    (
        "Cửa hàng cấm hoàn tiền với sản phẩm đã mở hộp.",
        "Sản phẩm đã mở hộp bị từ chối hoàn tiền.",
    ),
)
def test_citation_rejects_prohibition_synonyms(excerpt: str) -> None:
    source = replace(citation(), excerpt=excerpt)

    result = OutputVerifier().verify(
        answer="Sản phẩm đã mở hộp sẽ được hoàn tiền [KB-1].",
        citations=[source],
        policy_claims=True,
    )

    assert not result.valid
    assert "UNSUPPORTED_CITATION" in result.errors


def test_uncited_live_fact_prefix_is_allowed_beside_cited_policy() -> None:
    result = OutputVerifier().verify(
        answer=(
            "Theo dữ liệu hệ thống hiện tại, bảo hành đang còn hiệu lực. "
            "Sản phẩm cần giữ nguyên số serial để được tiếp nhận kiểm tra [KB-1]."
        ),
        citations=[citation()],
        policy_claims=True,
    )

    assert result.valid


def test_live_fact_prefix_cannot_hide_an_uncited_policy_claim() -> None:
    result = OutputVerifier().verify(
        answer=(
            "Theo dữ liệu hệ thống hiện tại, khách được hoàn tiền sau 90 ngày. "
            "Sản phẩm cần giữ nguyên số serial [KB-1]."
        ),
        citations=[citation()],
        policy_claims=True,
    )

    assert not result.valid
    assert "CITATION_REQUIRED" in result.errors


def test_reused_citation_label_must_support_every_attached_sentence() -> None:
    result = OutputVerifier().verify(
        answer=(
            "Sản phẩm cần giữ nguyên số serial để được tiếp nhận kiểm tra [KB-1]. "
            "Khách được hoàn tiền sau 90 ngày [KB-1]."
        ),
        citations=[citation()],
        policy_claims=True,
    )

    assert not result.valid
    assert "UNSUPPORTED_CITATION" in result.errors


def test_uncited_product_exchange_policy_sentence_is_rejected() -> None:
    result = OutputVerifier().verify(
        answer=("Cửa hàng hỗ trợ đổi sản phẩm lỗi. Sản phẩm cần giữ nguyên số serial [KB-1]."),
        citations=[citation()],
        policy_claims=True,
    )

    assert not result.valid
    assert "CITATION_REQUIRED" in result.errors


def test_unsupported_clause_cannot_hide_inside_supported_sentence() -> None:
    result = OutputVerifier().verify(
        answer=(
            "Sản phẩm cần giữ nguyên số serial để được tiếp nhận kiểm tra; "
            "khách được hoàn tiền [KB-1]."
        ),
        citations=[citation()],
        policy_claims=True,
    )

    assert not result.valid
    assert "UNSUPPORTED_CITATION" in result.errors


@pytest.mark.parametrize(
    "conjunction",
    ("và", "nhưng", "hoặc", "còn", "hay", "đồng thời", "trong khi"),
)
def test_unsupported_clause_cannot_hide_behind_conjunction(conjunction: str) -> None:
    result = OutputVerifier().verify(
        answer=(f"Sản phẩm cần giữ nguyên số serial {conjunction} khách được hoàn tiền [KB-1]."),
        citations=[citation()],
        policy_claims=True,
    )

    assert not result.valid
    assert "UNSUPPORTED_CITATION" in result.errors


def test_grounded_noun_list_joined_by_conjunction_is_valid() -> None:
    source = replace(
        citation(),
        excerpt="Sản phẩm cần giữ nguyên số serial và phụ kiện.",
    )

    result = OutputVerifier().verify(
        answer="Sản phẩm cần giữ nguyên số serial và phụ kiện [KB-1].",
        citations=[source],
        policy_claims=True,
    )

    assert result.valid


def test_multiple_citations_on_one_supported_claim_are_valid() -> None:
    second = replace(citation(), label="KB-2", document_id=uuid4(), chunk_id=uuid4())

    result = OutputVerifier().verify(
        answer=("Sản phẩm cần giữ nguyên số serial để được tiếp nhận kiểm tra [KB-1] [KB-2]."),
        citations=[citation(), second],
        policy_claims=True,
    )

    assert result.valid


def test_multiple_citations_can_collectively_cover_distinct_clauses() -> None:
    second = replace(
        citation(),
        label="KB-2",
        document_id=uuid4(),
        chunk_id=uuid4(),
        excerpt="Yêu cầu hoàn tiền phải gửi trong 7 ngày từ khi nhận hàng.",
    )

    result = OutputVerifier().verify(
        answer=(
            "Sản phẩm cần giữ nguyên số serial để được tiếp nhận kiểm tra; "
            "yêu cầu hoàn tiền phải gửi trong 7 ngày từ khi nhận hàng "
            "[KB-1] [KB-2]."
        ),
        citations=[citation(), second],
        policy_claims=True,
    )

    assert result.valid


def test_uncited_substantive_business_claim_is_rejected() -> None:
    result = OutputVerifier().verify(
        answer=("Cửa hàng tặng phụ kiện cao cấp. Sản phẩm cần giữ nguyên số serial [KB-1]."),
        citations=[citation()],
        policy_claims=True,
    )

    assert not result.valid
    assert "CITATION_REQUIRED" in result.errors


@pytest.mark.parametrize(
    "closing",
    (
        "Bạn cần tôi hỗ trợ thêm không?",
        "Bạn có câu hỏi nào khác không?",
        "Chúc bạn một ngày tốt lành.",
        "Nếu bạn cần hỗ trợ thêm, hãy cho tôi biết.",
        "Xin lỗi vì sự bất tiện.",
    ),
)
def test_conversational_closing_does_not_require_citation(closing: str) -> None:
    result = OutputVerifier().verify(
        answer=(f"Sản phẩm cần giữ nguyên số serial để được tiếp nhận kiểm tra [KB-1]. {closing}"),
        citations=[citation()],
        policy_claims=True,
    )

    assert result.valid


def test_conversational_prefix_cannot_hide_business_claim() -> None:
    result = OutputVerifier().verify(
        answer=(
            "Bạn cần tôi hỗ trợ hoàn tiền sau 90 ngày không? "
            "Sản phẩm cần giữ nguyên số serial [KB-1]."
        ),
        citations=[citation()],
        policy_claims=True,
    )

    assert not result.valid
    assert "CITATION_REQUIRED" in result.errors
