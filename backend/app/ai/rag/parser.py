from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader

from app.ai.rag.normalizer import normalize_text


class DocumentParseError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedPage:
    page: int | None
    text: str


def parse_document(
    content: bytes,
    media_type: str,
    *,
    max_pdf_pages: int = 200,
) -> list[ParsedPage]:
    if media_type in {"text/plain", "text/markdown"}:
        text = normalize_text(content.decode("utf-8"))
        if not text:
            raise DocumentParseError("Tài liệu không có nội dung văn bản.")
        return [ParsedPage(page=1, text=text)]

    if media_type != "application/pdf":
        raise DocumentParseError("Định dạng tài liệu không được hỗ trợ.")

    try:
        reader = PdfReader(BytesIO(content))
        if len(reader.pages) > max_pdf_pages:
            raise DocumentParseError("PDF vượt quá giới hạn số trang.")
        pages = [
            ParsedPage(page=index, text=normalize_text(page.extract_text() or ""))
            for index, page in enumerate(reader.pages, start=1)
        ]
    except Exception as error:
        raise DocumentParseError("Không thể đọc nội dung PDF.") from error
    non_empty = [page for page in pages if page.text]
    if not non_empty:
        raise DocumentParseError("PDF không chứa văn bản có thể trích xuất.")
    return non_empty
