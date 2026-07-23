from uuid import uuid4

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
        excerpt="Điều kiện đã được công bố.",
    )


def test_policy_answer_requires_known_citation_and_rejects_secrets() -> None:
    verifier = OutputVerifier()

    valid = verifier.verify(
        answer="Điều kiện đã được công bố [KB-1].",
        citations=[citation()],
        policy_claims=True,
    )
    missing = verifier.verify(
        answer="Điều kiện đã được công bố.",
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

