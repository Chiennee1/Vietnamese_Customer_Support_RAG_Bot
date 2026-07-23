from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
from math import ceil
from typing import Any


@dataclass(frozen=True, slots=True)
class LatencySummary:
    count: int
    average_ms: float
    p50_ms: int
    p95_ms: int
    maximum_ms: int


class MetricsRegistry:
    """Process-local operational metrics without user content or identifiers."""

    def __init__(self, *, latency_sample_limit: int = 10_000) -> None:
        self.requests: Counter[str] = Counter()
        self.chat_results: Counter[str] = Counter()
        self.chat_intents: Counter[str] = Counter()
        self.tool_calls: Counter[str] = Counter()
        self.feedback: Counter[str] = Counter()
        self.rag_results: Counter[str] = Counter()
        self.llm_models: Counter[str] = Counter()
        self.request_latencies: dict[str, deque[int]] = defaultdict(
            lambda: deque(maxlen=latency_sample_limit)
        )
        self.chat_latencies: deque[int] = deque(maxlen=latency_sample_limit)
        self.rag_latencies: deque[int] = deque(maxlen=latency_sample_limit)
        self.ticket_count = 0
        self.human_escalation_count = 0
        self.llm_usage_response_count = 0
        self.llm_input_tokens = 0
        self.llm_output_tokens = 0
        self.llm_estimated_cost_usd = 0.0

    def record_request(
        self,
        *,
        route: str,
        status_code: int,
        latency_ms: int,
    ) -> None:
        status_class = f"{status_code // 100}xx"
        self.requests[f"{route}|{status_class}"] += 1
        self.request_latencies[route].append(latency_ms)

    def record_chat(
        self,
        *,
        intent: str,
        status: str,
        latency_ms: int,
        tool_names: tuple[str, ...] = (),
        requires_human: bool = False,
        ticket_created: bool = False,
    ) -> None:
        self.chat_results[status] += 1
        self.chat_intents[intent] += 1
        self.chat_latencies.append(latency_ms)
        self.tool_calls.update(tool_names)
        if requires_human:
            self.human_escalation_count += 1
        if ticket_created:
            self.ticket_count += 1

    def record_feedback(self, rating: str) -> None:
        self.feedback[rating] += 1

    def record_rag(
        self,
        *,
        insufficient: bool,
        conflict: bool,
        retrieved_count: int,
        latency_ms: int,
    ) -> None:
        self.rag_results["requests"] += 1
        self.rag_results["no_result"] += int(insufficient)
        self.rag_results["conflict"] += int(conflict)
        self.rag_results["retrieved_items"] += retrieved_count
        self.rag_latencies.append(latency_ms)

    def record_llm_usage(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        estimated_cost_usd: float,
    ) -> None:
        self.llm_usage_response_count += 1
        self.llm_models[model] += 1
        self.llm_input_tokens += input_tokens
        self.llm_output_tokens += output_tokens
        self.llm_estimated_cost_usd += estimated_cost_usd

    def snapshot(self) -> dict[str, Any]:
        total_feedback = sum(self.feedback.values())
        total_chat = sum(self.chat_results.values())
        return {
            "api": {
                "requests": dict(sorted(self.requests.items())),
                "latency": {
                    route: asdict(self._latency(values))
                    for route, values in sorted(self.request_latencies.items())
                },
            },
            "chat": {
                "results": dict(sorted(self.chat_results.items())),
                "intents": dict(sorted(self.chat_intents.items())),
                "tools": dict(sorted(self.tool_calls.items())),
                "latency": asdict(self._latency(self.chat_latencies)),
                "human_escalation_rate": (
                    self.human_escalation_count / total_chat if total_chat else 0.0
                ),
                "tickets_created": self.ticket_count,
            },
            "rag": {
                **dict(sorted(self.rag_results.items())),
                "latency": asdict(self._latency(self.rag_latencies)),
            },
            "llm": {
                "responses_with_usage": self.llm_usage_response_count,
                "models": dict(sorted(self.llm_models.items())),
                "input_tokens": self.llm_input_tokens,
                "output_tokens": self.llm_output_tokens,
                "estimated_cost_usd": round(self.llm_estimated_cost_usd, 8),
            },
            "feedback": {
                "ratings": dict(sorted(self.feedback.items())),
                "positive_rate": (
                    self.feedback["positive"] / total_feedback if total_feedback else 0.0
                ),
            },
        }

    @staticmethod
    def _latency(values: deque[int]) -> LatencySummary:
        if not values:
            return LatencySummary(
                count=0,
                average_ms=0.0,
                p50_ms=0,
                p95_ms=0,
                maximum_ms=0,
            )
        ordered = sorted(values)

        def percentile(value: float) -> int:
            index = max(0, min(len(ordered) - 1, ceil(value * len(ordered)) - 1))
            return ordered[index]

        return LatencySummary(
            count=len(ordered),
            average_ms=round(sum(ordered) / len(ordered), 2),
            p50_ms=percentile(0.5),
            p95_ms=percentile(0.95),
            maximum_ms=ordered[-1],
        )
