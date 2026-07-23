import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum


class Route(StrEnum):
    KNOWLEDGE = "knowledge"
    CATALOG = "catalog"
    ACCOUNT = "account"
    SUPPORT = "support"
    UNKNOWN = "unknown"


class Intent(StrEnum):
    PRODUCT_SEARCH = "product_search"
    PRODUCT_PRICE = "product_price"
    PRODUCT_STOCK = "product_stock"
    WARRANTY_POLICY = "warranty_policy"
    RETURN_POLICY = "return_policy"
    SHIPPING_POLICY = "shipping_policy"
    PAYMENT_POLICY = "payment_policy"
    FAQ = "faq"
    ORDER_STATUS = "order_status"
    WARRANTY_STATUS = "warranty_status"
    COMPLAINT = "complaint"
    HUMAN_SUPPORT = "human_support"
    GREETING = "greeting"
    THANKS = "thanks"
    UNSAFE_REQUEST = "unsafe_request"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class RouteDecision:
    route: Route
    intent: Intent
    confidence: float
    allowed_tools: tuple[str, ...]


def normalize_for_routing(message: str) -> str:
    decomposed = unicodedata.normalize("NFD", message.casefold())
    without_marks = "".join(
        character
        for character in decomposed
        if unicodedata.category(character) != "Mn"
    )
    without_marks = without_marks.replace("đ", "d")
    return re.sub(r"\s+", " ", without_marks).strip()


class SupportRouter:
    unsafe_patterns = (
        "bo qua huong dan",
        "system prompt",
        "api key",
        "raw sql",
        "chay sql",
        "toan bo users",
        "quyen admin",
        "xuat toan bo database",
        "ignore previous",
        "dump database",
        "reveal prompt",
        "access token",
    )

    def route(self, message: str) -> RouteDecision:
        text = normalize_for_routing(message)
        if any(pattern in text for pattern in self.unsafe_patterns):
            return RouteDecision(Route.UNKNOWN, Intent.UNSAFE_REQUEST, 1.0, ())

        if any(
            term in text
            for term in ("khieu nai", "phong pin", "boc khoi", "chay no", "de doa")
        ):
            return RouteDecision(
                Route.SUPPORT,
                Intent.COMPLAINT,
                0.98,
                ("create_support_ticket", "search_knowledge_base"),
            )
        if any(
            term in text
            for term in (
                "gap nhan vien",
                "ho tro vien",
                "chuyen nguoi",
                "chuyen nhan vien",
                "tao ticket",
                "mo ticket",
            )
        ):
            return RouteDecision(
                Route.SUPPORT,
                Intent.HUMAN_SUPPORT,
                0.97,
                ("create_support_ticket",),
            )
        if re.search(r"\bSN[A-Z0-9_-]{4,}\b", message, re.IGNORECASE) or (
            "bao hanh" in text
            and (
                re.search(r"\bDH\d{6,}\b", message, re.IGNORECASE)
                or any(
                    term in text
                    for term in ("cua toi", "con", "serial", "may toi")
                )
            )
            and "chinh sach" not in text
        ):
            return RouteDecision(
                Route.ACCOUNT,
                Intent.WARRANTY_STATUS,
                0.97,
                ("check_warranty", "search_knowledge_base"),
            )
        if re.search(r"\bDH\d{6,}\b", message, re.IGNORECASE) or (
            "don" in text
            and any(term in text for term in ("trang thai", "giao", "toi dau"))
        ):
            return RouteDecision(
                Route.ACCOUNT,
                Intent.ORDER_STATUS,
                0.98,
                ("get_order_status",),
            )
        if "doi tra" in text or "hoan tra" in text:
            return RouteDecision(
                Route.KNOWLEDGE,
                Intent.RETURN_POLICY,
                0.96,
                ("search_knowledge_base",),
            )
        if "bao hanh" in text:
            return RouteDecision(
                Route.KNOWLEDGE,
                Intent.WARRANTY_POLICY,
                0.94,
                ("search_knowledge_base",),
            )
        if any(term in text for term in ("thanh toan", "otp", "the tin dung")):
            return RouteDecision(
                Route.KNOWLEDGE,
                Intent.PAYMENT_POLICY,
                0.95,
                ("search_knowledge_base",),
            )
        if any(term in text for term in ("giao hang", "van chuyen", "ship")):
            return RouteDecision(
                Route.KNOWLEDGE,
                Intent.SHIPPING_POLICY,
                0.9,
                ("search_knowledge_base",),
            )
        if any(term in text for term in ("con hang", "ton kho", "het hang")):
            return RouteDecision(
                Route.CATALOG,
                Intent.PRODUCT_STOCK,
                0.96,
                ("search_products",),
            )
        if any(term in text for term in ("gia bao nhieu", "gia", "bao nhieu tien")):
            return RouteDecision(
                Route.CATALOG,
                Intent.PRODUCT_PRICE,
                0.9,
                ("search_products",),
            )
        if any(
            term in text
            for term in ("dien thoai", "iphone", "samsung", "xiaomi", "oppo", "pixel")
        ):
            return RouteDecision(
                Route.CATALOG,
                Intent.PRODUCT_SEARCH,
                0.85,
                ("search_products",),
            )
        if text in {"xin chao", "chao", "hello", "hi"}:
            return RouteDecision(Route.UNKNOWN, Intent.GREETING, 1.0, ())
        if any(term in text for term in ("cam on", "thanks", "thank you")):
            return RouteDecision(Route.UNKNOWN, Intent.THANKS, 1.0, ())
        return RouteDecision(Route.UNKNOWN, Intent.UNKNOWN, 0.4, ())
