import asyncio
import re
from dataclasses import dataclass, field
from decimal import Decimal
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
    WarrantyAssessment,
    WarrantyStatusInput,
    WarrantyStatusOutput,
)
from app.core.errors import AppError
from app.db.models.conversation import ToolExecutionStatus
from app.db.models.ticket import TicketSeverity
from app.db.models.warranty import WarrantyStatus
from app.services.tickets import TicketCreationOutput

IDENTIFIER_PATTERN = re.compile(
    r"\b(?:DH\d{6,}|SN[A-Z0-9_-]{4,}|[A-Z]{3}-\d{3}-\d|[A-Z]{2,8}-\d{2,8})\b",
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
    status: ToolExecutionStatus = ToolExecutionStatus.SUCCESS
    error_code: str | None = None


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
    warranty_assessment: WarrantyAssessment | None = None
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
        if decision.intent == Intent.UNKNOWN and self._is_ticket_confirmation(message, history):
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
        requires_human = False
        human_reason: str | None = None
        suggested_actions: tuple[str, ...] = ()
        warranty_assessment: WarrantyAssessment | None = None

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
            knowledge = self._expect(
                knowledge,
                KnowledgeSearchOutput,
                tool_executions,
            )
            if knowledge.insufficient:
                return OrchestratorResult(
                    answer=(
                        "Tôi chưa thể xác minh câu trả lời từ knowledge base đã được phê duyệt."
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
                self._product_search_input(message),
                context,
                decision,
                "search_products",
                tool_names,
                tool_executions,
            )
            products = self._expect(
                products,
                ProductSearchOutput,
                tool_executions,
            )
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
            order = self._expect(order, OrderStatusOutput, tool_executions)
            trusted_context["current_order"] = order.model_dump(mode="json")
            if "search_knowledge_base" in decision.allowed_tools:
                policy_claims = True
                knowledge = await self._execute(
                    self.tools.knowledge,
                    KnowledgeSearchInput(
                        query=message,
                        category=self._order_policy_category(message),
                    ),
                    context,
                    decision,
                    "search_knowledge_base",
                    tool_names,
                    tool_executions,
                )
                knowledge = self._expect(
                    knowledge,
                    KnowledgeSearchOutput,
                    tool_executions,
                )
                if knowledge.insufficient:
                    return OrchestratorResult(
                        answer=(
                            f"Đơn {order.order_code} hiện có trạng thái "
                            f"{order.status.value}, nhưng tôi chưa thể xác minh "
                            "điều kiện chính sách áp dụng từ knowledge base đã phê duyệt."
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
                            f"Đơn {order.order_code} hiện có trạng thái "
                            f"{order.status.value}. Tài liệu chính sách liên quan "
                            "chưa thống nhất nên cần nhân viên xác minh."
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
            warranty = self._expect(
                warranty,
                WarrantyStatusOutput,
                tool_executions,
            )
            knowledge = await self._execute(
                self.tools.knowledge,
                KnowledgeSearchInput(
                    query=f"Điều kiện bảo hành áp dụng: {message}"[:500],
                    category="warranty",
                ),
                context,
                decision,
                "search_knowledge_base",
                tool_names,
                tool_executions,
            )
            knowledge = self._expect(
                knowledge,
                KnowledgeSearchOutput,
                tool_executions,
            )
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
                    warranty_assessment=WarrantyAssessment.NEEDS_MANUAL_REVIEW,
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
                    warranty_assessment=WarrantyAssessment.NEEDS_MANUAL_REVIEW,
                    tool_executions=tuple(tool_executions),
                )
            policy_claims = True
            trusted_context["policy_evidence"] = knowledge.model_dump(mode="json")
            citations = self._citations(knowledge)
            warranty_assessment = self._warranty_assessment(
                warranty.status,
                message,
                knowledge,
            )
            trusted_context["warranty_assessment"] = {
                "outcome": warranty_assessment.value,
                "meaning": (
                    "Đánh giá sơ bộ theo trạng thái và evidence để tiếp nhận; "
                    "không phải phê duyệt "
                    "bảo hành, đổi máy hoặc bồi thường."
                ),
            }
            if warranty_assessment != WarrantyAssessment.ELIGIBLE:
                requires_human = True
                human_reason = (
                    "WARRANTY_EXPIRED"
                    if warranty_assessment == WarrantyAssessment.INELIGIBLE
                    else "WARRANTY_MANUAL_REVIEW"
                )
                suggested_actions = ("contact_support",)

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

        try:
            answer = await self.model.generate(
                GenerationRequest(
                    intent=decision.intent.value,
                    user_message=message,
                    trusted_context=trusted_context,
                    citations=citations,
                    history=history[-10:],
                )
            )
        except AppError as error:
            self._attach_traces(error, tool_executions)
            raise
        except Exception as error:
            wrapped = AppError(
                code="MODEL_EXECUTION_FAILED",
                message="Dịch vụ tạo câu trả lời hiện không khả dụng.",
                status_code=502,
            )
            self._attach_traces(wrapped, tool_executions)
            raise wrapped from error
        verification = self.verifier.verify(
            answer=answer,
            citations=citations,
            policy_claims=policy_claims,
        )
        if not verification.valid:
            verification_error = AppError(
                code="OUTPUT_VERIFICATION_FAILED",
                message="Không thể xác minh câu trả lời trước khi gửi.",
                status_code=502,
            )
            self._attach_traces(verification_error, tool_executions)
            raise verification_error
        return OrchestratorResult(
            answer=answer,
            intent=decision.intent.value,
            citations=citations,
            requires_human=requires_human,
            human_reason=human_reason,
            suggested_actions=suggested_actions,
            tool_names=tuple(tool_names),
            warranty_assessment=warranty_assessment,
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
            ticket = self._expect(
                ticket,
                TicketCreationOutput,
                tool_executions,
            )
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
                "SAFETY_RISK" if severity == TicketSeverity.CRITICAL else "CUSTOMER_COMPLAINT"
            ),
            suggested_actions=(() if ticket_code else ("confirm_ticket_creation",)),
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
        tool_names.append(name)
        started = perf_counter()
        try:
            async with asyncio.timeout(self.tool_timeout_seconds):
                result = await tool.execute(payload, context)
        except TimeoutError as error:
            self._record_trace(
                context,
                tool_executions,
                ToolExecutionTrace(
                    name=name,
                    duration_ms=max(
                        0,
                        round((perf_counter() - started) * 1000),
                    ),
                    status=ToolExecutionStatus.TIMEOUT,
                    error_code="TOOL_TIMEOUT",
                ),
            )
            wrapped = AppError(
                code="TOOL_TIMEOUT",
                message="Dịch vụ tra cứu phản hồi quá thời gian.",
                status_code=504,
            )
            self._attach_traces(wrapped, tool_executions)
            raise wrapped from error
        except AppError as error:
            self._record_trace(
                context,
                tool_executions,
                ToolExecutionTrace(
                    name=name,
                    duration_ms=max(0, round((perf_counter() - started) * 1000)),
                    status=ToolExecutionStatus.FAILED,
                    error_code=error.code,
                ),
            )
            self._attach_traces(error, tool_executions)
            raise
        except Exception as error:
            self._record_trace(
                context,
                tool_executions,
                ToolExecutionTrace(
                    name=name,
                    duration_ms=max(0, round((perf_counter() - started) * 1000)),
                    status=ToolExecutionStatus.FAILED,
                    error_code="TOOL_EXECUTION_FAILED",
                ),
            )
            wrapped = AppError(
                code="TOOL_EXECUTION_FAILED",
                message="Dịch vụ tra cứu hiện không khả dụng.",
                status_code=502,
            )
            self._attach_traces(wrapped, tool_executions)
            raise wrapped from error
        self._record_trace(
            context,
            tool_executions,
            ToolExecutionTrace(
                name=name,
                duration_ms=max(0, round((perf_counter() - started) * 1000)),
            ),
        )
        return result

    @staticmethod
    def _expect(
        value: Any,
        expected: type[BaseModel],
        traces: list[ToolExecutionTrace],
    ) -> Any:
        if not isinstance(value, expected):
            error = AppError(
                code="INVALID_TOOL_RESULT",
                message="Kết quả hệ thống không hợp lệ.",
                status_code=502,
            )
            SupportOrchestrator._attach_traces(error, traces)
            raise error
        return value

    @staticmethod
    def _record_trace(
        context: RuntimeContext,
        traces: list[ToolExecutionTrace],
        trace: ToolExecutionTrace,
    ) -> None:
        traces.append(trace)
        if context.tool_trace_sink is not None:
            context.tool_trace_sink.append(
                {
                    "name": trace.name,
                    "duration_ms": trace.duration_ms,
                    "status": trace.status.value,
                    "error_code": trace.error_code,
                }
            )

    @staticmethod
    def _citations(knowledge: KnowledgeSearchOutput) -> list[Citation]:
        return [Citation(**citation.model_dump()) for citation in knowledge.citations]

    @staticmethod
    def _identifier(message: str, prefix: str | None = None) -> str | None:
        for match in IDENTIFIER_PATTERN.finditer(message):
            value = match.group(0).upper()
            if prefix is None or value.startswith(prefix):
                return value
        return None

    @staticmethod
    def _product_search_input(message: str) -> ProductSearchInput:
        identifier = SupportOrchestrator._identifier(message)
        if identifier and not identifier.startswith(("DH", "SN")):
            return ProductSearchInput(query=identifier)
        normalized = normalize_for_routing(message)
        brand: str | None = None
        for source, replacement in (
            ("iphone", "Apple"),
            ("samsung", "Samsung"),
            ("xiaomi", "Xiaomi"),
            ("oppo", "OPPO"),
            ("pixel", "Google"),
        ):
            if source in normalized:
                brand = replacement
                break
        storage_match = re.search(r"\b(\d{2,4})\s*(?:gb|g)\b", normalized)
        storage_gb = int(storage_match.group(1)) if storage_match else None
        price_match = re.search(
            r"\b(?:duoi|khong qua|toi da|tam|khoang)\s*"
            r"(\d+(?:[.,]\d+)?)\s*(?:trieu|tr)\b",
            normalized,
        )
        max_price = (
            Decimal(price_match.group(1).replace(",", ".")) * Decimal("1000000")
            if price_match
            else None
        )
        color = next(
            (
                canonical
                for term, canonical in (
                    ("titan tu nhien", "Titan tự nhiên"),
                    ("den", "Đen"),
                    ("trang", "Trắng"),
                    ("xanh", "Xanh"),
                    ("tim", "Tím"),
                )
                if re.search(rf"\b{term}\b", normalized)
            ),
            None,
        )
        return ProductSearchInput(
            query=message[:200],
            brand=brand,
            max_price=max_price,
            storage_gb=storage_gb,
            color=color,
        )

    @staticmethod
    def _policy_category(intent: Intent) -> str | None:
        return {
            Intent.WARRANTY_POLICY: "warranty",
            Intent.RETURN_POLICY: "returns",
            Intent.SHIPPING_POLICY: "shipping",
            Intent.PAYMENT_POLICY: "payment",
            Intent.FAQ: None,
        }.get(intent)

    @staticmethod
    def _order_policy_category(message: str) -> str:
        normalized = normalize_for_routing(message)
        if any(
            term in normalized
            for term in (
                "doi tra",
                "doi may",
                "hoan tra",
                "hoan tien",
                "tra hang",
            )
        ):
            return "returns"
        if "thanh toan" in normalized:
            return "payment"
        return "shipping"

    @staticmethod
    def _warranty_assessment(
        status: WarrantyStatus,
        message: str,
        knowledge: KnowledgeSearchOutput,
    ) -> WarrantyAssessment:
        if status == WarrantyStatus.EXPIRED:
            return WarrantyAssessment.INELIGIBLE
        if status != WarrantyStatus.ACTIVE:
            return WarrantyAssessment.NEEDS_MANUAL_REVIEW
        normalized = normalize_for_routing(message)
        manual_review_terms = (
            "roi",
            "vo",
            "nuoc",
            "chat long",
            "mop",
            "nut",
            "sua ngoai",
            "phong pin",
            "boc khoi",
        )
        if any(term in normalized for term in manual_review_terms):
            return WarrantyAssessment.NEEDS_MANUAL_REVIEW
        evidence = normalize_for_routing(" ".join(knowledge.evidence))
        if "con thoi han" in evidence and "tiep nhan" in evidence:
            return WarrantyAssessment.ELIGIBLE
        return WarrantyAssessment.NEEDS_MANUAL_REVIEW

    @staticmethod
    def _attach_traces(
        error: AppError,
        traces: list[ToolExecutionTrace],
    ) -> None:
        context = dict(error.internal_context or {})
        context["tool_executions"] = [
            {
                "name": trace.name,
                "duration_ms": trace.duration_ms,
                "status": trace.status.value,
                "error_code": trace.error_code,
            }
            for trace in traces
        ]
        error.internal_context = context

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
        return last_turn.role == "assistant" and "tao ticket" in normalize_for_routing(
            last_turn.content
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
