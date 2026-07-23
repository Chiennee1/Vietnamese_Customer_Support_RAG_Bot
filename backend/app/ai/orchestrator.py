import asyncio
import re
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Protocol

from pydantic import BaseModel

from app.ai.model import (
    ConversationTurn,
    ModelProvider,
)
from app.ai.model import (
    GenerationRequest as GenerationRequest,
)
from app.ai.output_verifier import OutputVerifier
from app.ai.rag.citations import Citation
from app.ai.router import (
    Intent,
    Route,
    RouteDecision,
    SupportRouter,
    normalize_for_routing,
)
from app.ai.tools.contracts import (
    KnowledgeSearchInput,
    KnowledgeSearchOutput,
    OrderStatusInput,
    OrderStatusOutput,
    ProductSearchInput,
    ProductSearchOutput,
    RuntimeContext,
    TicketCreationInput,
    WarrantyStatusInput,
    WarrantyStatusOutput,
)
from app.core.errors import AppError
from app.db.models.ticket import TicketSeverity
from app.services.tickets import TicketCreationOutput

IDENTIFIER_PATTERN = re.compile(
    r"\b(?:DH\d{6,}|SN[A-Z0-9_-]{4,}|[A-Z]{3}-\d{3}-\d)\b",
    re.IGNORECASE,
)


class ToolExecutor(Protocol):
    async def execute(self, payload: Any, context: RuntimeContext) -> Any: ...


@dataclass(frozen=True, slots=True)
class OrchestratorTools:
    products: ToolExecutor
    orders: ToolExecutor
    warranties: ToolExecutor
    knowledge: ToolExecutor
    tickets: ToolExecutor


@dataclass(frozen=True, slots=True)
class ToolExecutionTrace:
    name: str
    duration_ms: int


@dataclass(frozen=True, slots=True)
class OrchestratorResult:
    answer: str
    intent: str
    citations: list[Citation]
    requires_human: bool
    human_reason: str | None
    suggested_actions: tuple[str, ...]
    tool_names: tuple[str, ...]
    ticket_code: str | None = None
    tool_executions: tuple[ToolExecutionTrace, ...] = field(default_factory=tuple)
    model_used: bool = False


class SupportOrchestrator:
    def __init__(
        self,
        *,
        router: SupportRouter,
        tools: OrchestratorTools,
        model: ModelProvider,
        max_tool_calls: int,
        tool_timeout_seconds: float = 8,
        verifier: OutputVerifier | None = None,
    ) -> None:
        self.router = router
        self.tools = tools
        self.model = model
        self.max_tool_calls = max_tool_calls
        self.tool_timeout_seconds = tool_timeout_seconds
        self.verifier = verifier or OutputVerifier()

    async def respond(
        self,
        message: str,
        *,
        context: RuntimeContext,
        history: tuple[ConversationTurn, ...] = (),
    ) -> OrchestratorResult:
        if not message.strip() or len(message) > 2_000:
            raise AppError(
                code="INVALID_MESSAGE",
                message="Tin nhắn phải có từ 1 đến 2.000 ký tự.",
                status_code=422,
            )
        decision = self.router.route(message)
        if (
            decision.intent == Intent.UNKNOWN
            and self._is_ticket_confirmation(message, history)
        ):
            decision = RouteDecision(
                route=Route.SUPPORT,
                intent=Intent.HUMAN_SUPPORT,
                confidence=0.99,
                allowed_tools=("create_support_ticket",),
            )
        if decision.intent == Intent.UNSAFE_REQUEST:
            return self._direct(
                "Tôi không thể thực hiện yêu cầu truy cập dữ liệu, SQL, "
                "quyền hạn hoặc thông tin bảo mật.",
                decision,
            )
        if decision.intent == Intent.GREETING:
            return self._direct(
                "Xin chào! Tôi có thể hỗ trợ sản phẩm, đơn hàng, bảo hành "
                "và chính sách của cửa hàng.",
                decision,
            )
        if decision.intent == Intent.THANKS:
            return self._direct("Rất vui được hỗ trợ bạn.", decision)
        if decision.intent == Intent.UNKNOWN:
            return self._direct(
                "Tôi chỉ hỗ trợ sản phẩm, đơn hàng, bảo hành, chính sách "
                "và khiếu nại của cửa hàng.",
                decision,
            )

        tool_names: list[str] = []
        tool_executions: list[ToolExecutionTrace] = []
        trusted_context: dict[str, Any] = {}
        citations: list[Citation] = []
        policy_claims = False

        if decision.intent in {
            Intent.WARRANTY_POLICY,
            Intent.RETURN_POLICY,
            Intent.SHIPPING_POLICY,
            Intent.PAYMENT_POLICY,
            Intent.FAQ,
        }:
            policy_claims = True
            knowledge = await self._execute(
                self.tools.knowledge,
                KnowledgeSearchInput(
                    query=message,
                    category=self._policy_category(decision.intent),
                ),
                context,
                decision,
                "search_knowledge_base",
                tool_names,
                tool_executions,
            )
            knowledge = self._expect(knowledge, KnowledgeSearchOutput)
            if knowledge.insufficient:
                return OrchestratorResult(
                    answer=(
                        "Tôi chưa thể xác minh câu trả lời từ knowledge base "
                        "đã được phê duyệt."
                    ),
                    intent=decision.intent.value,
                    citations=[],
                    requires_human=False,
                    human_reason=None,
                    suggested_actions=(),
                    tool_names=tuple(tool_names),
                    tool_executions=tuple(tool_executions),
                )
            if knowledge.conflict:
                return OrchestratorResult(
                    answer=(
                        "Các tài liệu hiện hành có thông tin chưa thống nhất. "
                        "Vấn đề này cần nhân viên kiểm tra."
                    ),
                    intent=decision.intent.value,
                    citations=self._citations(knowledge),
                    requires_human=True,
                    human_reason="KNOWLEDGE_CONFLICT",
                    suggested_actions=("contact_support",),
                    tool_names=tuple(tool_names),
                    tool_executions=tuple(tool_executions),
                )
            trusted_context["policy_evidence"] = knowledge.model_dump(mode="json")
            citations = self._citations(knowledge)

        elif decision.intent in {
            Intent.PRODUCT_SEARCH,
            Intent.PRODUCT_PRICE,
            Intent.PRODUCT_STOCK,
        }:
            products = await self._execute(
                self.tools.products,
                ProductSearchInput(query=self._product_query(message)),
                context,
                decision,
                "search_products",
                tool_names,
                tool_executions,
            )
            products = self._expect(products, ProductSearchOutput)
            trusted_context["current_products"] = products.model_dump(mode="json")

        elif decision.intent == Intent.ORDER_STATUS:
            identifier = self._identifier(message, prefix="DH")
            if identifier is None:
                return self._direct(
                    "Vui lòng cung cấp mã đơn hàng để tôi kiểm tra.",
                    decision,
                )
            order = await self._execute(
                self.tools.orders,
                OrderStatusInput(order_code=identifier),
                context,
                decision,
                "get_order_status",
                tool_names,
                tool_executions,
            )
            order = self._expect(order, OrderStatusOutput)
            trusted_context["current_order"] = order.model_dump(mode="json")

        elif decision.intent == Intent.WARRANTY_STATUS:
            identifier = self._identifier(message)
            if identifier is None:
                return self._direct(
                    "Vui lòng cung cấp số serial hoặc mã đơn để tôi kiểm tra bảo hành.",
                    decision,
                )
            warranty = await self._execute(
                self.tools.warranties,
                WarrantyStatusInput(identifier=identifier),
                context,
                decision,
                "check_warranty",
                tool_names,
                tool_executions,
            )
            warranty = self._expect(warranty, WarrantyStatusOutput)
            knowledge = await self._execute(
                self.tools.knowledge,
                KnowledgeSearchInput(
                    query="Điều kiện và quy trình bảo hành",
                    category="warranty",
                ),
                context,
                decision,
                "search_knowledge_base",
                tool_names,
                tool_executions,
            )
            knowledge = self._expect(knowledge, KnowledgeSearchOutput)
            trusted_context["current_warranty"] = warranty.model_dump(mode="json")
            if knowledge.insufficient:
                return OrchestratorResult(
                    answer=(
                        f"Trạng thái bảo hành hiện tại là {warranty.status.value}, "
                        "nhưng tôi chưa thể xác minh các điều kiện áp dụng từ "
                        "knowledge base đã phê duyệt."
                    ),
                    intent=decision.intent.value,
                    citations=[],
                    requires_human=True,
                    human_reason="KNOWLEDGE_INSUFFICIENT",
                    suggested_actions=("contact_support",),
                    tool_names=tuple(tool_names),
                    tool_executions=tuple(tool_executions),
                )
            if knowledge.conflict or knowledge.requires_human:
                return OrchestratorResult(
                    answer=(
                        "Dữ liệu chính sách bảo hành hiện có thông tin chưa thống nhất. "
                        "Trạng thái trong hệ thống đã được kiểm tra, nhưng điều kiện áp dụng "
                        "cần nhân viên xác minh."
                    ),
                    intent=decision.intent.value,
                    citations=self._citations(knowledge),
                    requires_human=True,
                    human_reason="KNOWLEDGE_CONFLICT",
                    suggested_actions=("contact_support",),
                    tool_names=tuple(tool_names),
                    tool_executions=tuple(tool_executions),
                )
            policy_claims = True
            trusted_context["policy_evidence"] = knowledge.model_dump(mode="json")
            citations = self._citations(knowledge)

        elif decision.intent in {Intent.COMPLAINT, Intent.HUMAN_SUPPORT}:
            return await self._handle_support(
                message,
                context=context,
                decision=decision,
                tool_names=tool_names,
                tool_executions=tool_executions,
                history=history,
            )

        else:
            return self._direct("Tôi chưa thể xử lý yêu cầu này.", decision)

        answer = await self.model.generate(
            GenerationRequest(
                intent=decision.intent.value,
                user_message=message,
                trusted_context=trusted_context,
                citations=citations,
                history=history[-10:],
            )
        )
        verification = self.verifier.verify(
            answer=answer,
            citations=citations,
            policy_claims=policy_claims,
        )
        if not verification.valid:
            raise AppError(
                code="OUTPUT_VERIFICATION_FAILED",
                message="Không thể xác minh câu trả lời trước khi gửi.",
                status_code=502,
            )
        return OrchestratorResult(
            answer=answer,
            intent=decision.intent.value,
            citations=citations,
            requires_human=False,
            human_reason=None,
            suggested_actions=(),
            tool_names=tuple(tool_names),
            tool_executions=tuple(tool_executions),
            model_used=True,
        )

    async def _handle_support(
        self,
        message: str,
        *,
        context: RuntimeContext,
        decision: RouteDecision,
        tool_names: list[str],
        tool_executions: list[ToolExecutionTrace],
        history: tuple[ConversationTurn, ...],
    ) -> OrchestratorResult:
        normalized = normalize_for_routing(message)
        confirmation = self._is_ticket_confirmation(message, history)
        explicit = confirmation or any(
            phrase in normalized
            for phrase in (
                "tao ticket",
                "mo ticket",
                "lap ticket",
                "hay tao ticket",
                "chuyen nhan vien",
                "gap nhan vien",
                "dong y tao",
            )
        )
        ticket_code: str | None = None
        issue_summary = self._support_summary(message, history) if confirmation else message
        severity = self._severity(issue_summary)
        if explicit:
            ticket = await self._execute(
                self.tools.tickets,
                TicketCreationInput(
                    category=(
                        "safety_incident"
                        if severity == TicketSeverity.CRITICAL
                        else "customer_complaint"
                    ),
                    subject="Yêu cầu hỗ trợ từ hội thoại",
                    summary=issue_summary,
                    severity=severity,
                ),
                context,
                decision,
                "create_support_ticket",
                tool_names,
                tool_executions,
            )
            ticket = self._expect(ticket, TicketCreationOutput)
            ticket_code = ticket.ticket_code

        if severity == TicketSeverity.CRITICAL:
            answer = (
                "Tôi đã ghi nhận tình huống có nguy cơ an toàn. Hãy ngừng sử dụng "
                "và không sạc thiết bị; không tự tháo máy. "
            )
        else:
            answer = "Tôi đã ghi nhận vấn đề của bạn. "
        if ticket_code:
            answer += f"Yêu cầu hỗ trợ {ticket_code} đã được tạo để nhân viên xem xét."
        else:
            answer += "Bạn có muốn tôi tạo ticket để chuyển nhân viên xem xét không?"
        return OrchestratorResult(
            answer=answer,
            intent=decision.intent.value,
            citations=[],
            requires_human=True,
            human_reason=(
                "SAFETY_RISK"
                if severity == TicketSeverity.CRITICAL
                else "CUSTOMER_COMPLAINT"
            ),
            suggested_actions=(
                () if ticket_code else ("confirm_ticket_creation",)
            ),
            tool_names=tuple(tool_names),
            ticket_code=ticket_code,
            tool_executions=tuple(tool_executions),
        )

    async def _execute(
        self,
        tool: ToolExecutor,
        payload: BaseModel,
        context: RuntimeContext,
        decision: RouteDecision,
        name: str,
        tool_names: list[str],
        tool_executions: list[ToolExecutionTrace],
    ) -> Any:
        if name not in decision.allowed_tools:
            raise AppError(
                code="FORBIDDEN_TOOL",
                message="Công cụ không được phép cho yêu cầu này.",
                status_code=403,
            )
        if len(tool_names) >= self.max_tool_calls:
            raise AppError(
                code="TOOL_LIMIT_EXCEEDED",
                message="Yêu cầu vượt quá giới hạn xử lý an toàn.",
                status_code=429,
            )
        started = perf_counter()
        try:
            async with asyncio.timeout(self.tool_timeout_seconds):
                result = await tool.execute(payload, context)
        except TimeoutError as error:
            raise AppError(
                code="TOOL_TIMEOUT",
                message="Dịch vụ tra cứu phản hồi quá thời gian.",
                status_code=504,
            ) from error
        tool_names.append(name)
        tool_executions.append(
            ToolExecutionTrace(
                name=name,
                duration_ms=max(0, round((perf_counter() - started) * 1000)),
            )
        )
        return result

    @staticmethod
    def _expect(value: Any, expected: type[BaseModel]) -> Any:
        if not isinstance(value, expected):
            raise AppError(
                code="INVALID_TOOL_RESULT",
                message="Kết quả hệ thống không hợp lệ.",
                status_code=502,
            )
        return value

    @staticmethod
    def _citations(knowledge: KnowledgeSearchOutput) -> list[Citation]:
        return [
            Citation(**citation.model_dump())
            for citation in knowledge.citations
        ]

    @staticmethod
    def _identifier(message: str, prefix: str | None = None) -> str | None:
        for match in IDENTIFIER_PATTERN.finditer(message):
            value = match.group(0).upper()
            if prefix is None or value.startswith(prefix):
                return value
        return None

    @staticmethod
    def _product_query(message: str) -> str:
        identifier = SupportOrchestrator._identifier(message)
        if identifier and not identifier.startswith(("DH", "SN")):
            return identifier
        normalized = normalize_for_routing(message)
        for source, replacement in (
            ("iphone", "Apple"),
            ("samsung", "Samsung"),
            ("xiaomi", "Xiaomi"),
            ("oppo", "OPPO"),
            ("pixel", "Google"),
        ):
            if source in normalized:
                return replacement
        return message[:200]

    @staticmethod
    def _policy_category(intent: Intent) -> str | None:
        return {
            Intent.WARRANTY_POLICY: "warranty",
            Intent.RETURN_POLICY: "returns",
            Intent.SHIPPING_POLICY: "shipping",
            Intent.PAYMENT_POLICY: "payment",
            Intent.FAQ: "faq",
        }.get(intent)

    @staticmethod
    def _is_ticket_confirmation(
        message: str,
        history: tuple[ConversationTurn, ...],
    ) -> bool:
        normalized = normalize_for_routing(message)
        confirmations = {
            "dong y",
            "dong y tao ticket",
            "duoc",
            "ok",
            "tao di",
            "hay tao",
        }
        if normalized not in confirmations or not history:
            return False
        last_turn = history[-1]
        return (
            last_turn.role == "assistant"
            and "tao ticket" in normalize_for_routing(last_turn.content)
        )

    @staticmethod
    def _support_summary(
        message: str,
        history: tuple[ConversationTurn, ...],
    ) -> str:
        for turn in reversed(history):
            if turn.role == "user" and len(turn.content.strip()) >= 5:
                return turn.content.strip()[:1000]
        return message.strip()[:1000]

    @staticmethod
    def _severity(message: str) -> TicketSeverity:
        normalized = normalize_for_routing(message)
        if any(
            term in normalized
            for term in (
                "phong pin",
                "boc khoi",
                "chay no",
                "mui khet",
                "ro dien",
                "lo du lieu",
            )
        ):
            return TicketSeverity.CRITICAL
        if any(
            term in normalized
            for term in ("nhieu lan", "lap lai", "tranh chap", "luat su", "de doa")
        ):
            return TicketSeverity.HIGH
        return TicketSeverity.NORMAL

    @staticmethod
    def _direct(answer: str, decision: RouteDecision) -> OrchestratorResult:
        return OrchestratorResult(
            answer=answer,
            intent=decision.intent.value,
            citations=[],
            requires_human=False,
            human_reason=None,
            suggested_actions=(),
            tool_names=(),
        )
