import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.ai.router import SupportRouter


@dataclass(frozen=True, slots=True)
class AgentGoldCase:
    id: str
    message: str
    expected_intent: str
    expected_tools: tuple[str, ...]
    critical: bool


@dataclass(frozen=True, slots=True)
class AgentMetrics:
    cases: int
    intent_accuracy: float
    tool_accuracy: float
    critical_bypasses: int


def load_agent_gold_cases(path: Path) -> list[AgentGoldCase]:
    cases: list[AgentGoldCase] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            payload: dict[str, Any] = json.loads(line)
            tools = payload.get("expected_tools", [])
            if not isinstance(tools, list):
                raise TypeError("expected_tools must be a list")
            case = AgentGoldCase(
                id=str(payload["id"]),
                message=str(payload["message"]),
                expected_intent=str(payload["expected_intent"]),
                expected_tools=tuple(str(tool) for tool in tools),
                critical=bool(payload.get("critical", False)),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(
                f"invalid agent gold case at line {line_number}"
            ) from error
        if case.id in seen_ids:
            raise ValueError(f"duplicate agent gold case id: {case.id}")
        if not case.message.strip():
            raise ValueError(f"agent gold case {case.id} has an empty message")
        seen_ids.add(case.id)
        cases.append(case)
    if not cases:
        raise ValueError("agent gold dataset is empty")
    return cases


def evaluate_router(
    cases: list[AgentGoldCase],
    *,
    router: SupportRouter | None = None,
) -> AgentMetrics:
    if not cases:
        raise ValueError("at least one agent case is required")
    resolved_router = router or SupportRouter()
    intent_matches = 0
    tool_matches = 0
    critical_bypasses = 0
    for case in cases:
        decision = resolved_router.route(case.message)
        intent_match = decision.intent.value == case.expected_intent
        tool_match = decision.allowed_tools == case.expected_tools
        intent_matches += int(intent_match)
        tool_matches += int(tool_match)
        if case.critical and (not intent_match or not tool_match):
            critical_bypasses += 1
    count = len(cases)
    return AgentMetrics(
        cases=count,
        intent_accuracy=intent_matches / count,
        tool_accuracy=tool_matches / count,
        critical_bypasses=critical_bypasses,
    )
