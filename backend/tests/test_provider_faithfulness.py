from app.ai.model import GenerationRequest
from app.evaluation.faithfulness import FaithfulnessGoldCase
from app.evaluation.provider_faithfulness import evaluate_provider_faithfulness


class RecordedModel:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.requests: list[GenerationRequest] = []

    async def generate(self, request: GenerationRequest) -> str:
        self.requests.append(request)
        return self.outputs.pop(0)


def case(case_id: str) -> FaithfulnessGoldCase:
    return FaithfulnessGoldCase(
        id=case_id,
        question="Khách hàng có bao nhiêu ngày để gửi yêu cầu đổi trả?",
        answer="Khách hàng có 7 ngày theo lịch để gửi yêu cầu đổi trả [KB-1].",
        expected_valid=True,
        title="Chính sách đổi trả",
        section="Thời gian gửi yêu cầu",
        excerpt="Khách hàng có thể gửi yêu cầu đổi trả trong vòng 7 ngày theo lịch.",
    )


async def test_provider_faithfulness_scores_generated_answers_and_citations() -> None:
    model = RecordedModel(
        [
            "Khách hàng có 7 ngày theo lịch để gửi yêu cầu đổi trả [KB-1].",
            "Khách hàng có 30 ngày để gửi yêu cầu đổi trả [KB-9].",
        ]
    )

    report = await evaluate_provider_faithfulness(
        [case("one"), case("two")],
        model=model,
        model_name="recorded-test-model",
    )

    assert report.cases == 2
    assert report.faithfulness == 0.5
    assert report.citation_validity == 0.5
    assert not report.passed
    assert len(model.requests) == 2
    assert model.requests[0].citations[0].label == "KB-1"
