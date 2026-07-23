import hashlib
from dataclasses import dataclass
from pathlib import PurePath

ALLOWED_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
}


class UploadValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    filename: str
    media_type: str
    content: bytes
    checksum: str


def validate_upload(
    *,
    filename: str,
    declared_media_type: str,
    content: bytes,
    max_bytes: int,
) -> ValidatedUpload:
    if not content:
        raise UploadValidationError("Tệp tải lên đang trống.")
    if len(content) > max_bytes:
        raise UploadValidationError("Tệp tải lên vượt quá giới hạn dung lượng.")
    if (
        not filename
        or filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or PurePath(filename).name != filename
        or ".." in PurePath(filename).parts
    ):
        raise UploadValidationError("Tên tệp không hợp lệ.")

    extension = PurePath(filename).suffix.lower()
    expected_media_type = ALLOWED_MEDIA_TYPES.get(extension)
    if expected_media_type is None or declared_media_type != expected_media_type:
        raise UploadValidationError("Định dạng tệp không được hỗ trợ.")

    if expected_media_type == "application/pdf":
        if not content.startswith(b"%PDF-"):
            raise UploadValidationError("Nội dung tệp PDF không hợp lệ.")
    else:
        try:
            decoded = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise UploadValidationError("Tệp văn bản phải dùng UTF-8.") from error
        if "\x00" in decoded:
            raise UploadValidationError("Tệp văn bản chứa dữ liệu nhị phân.")

    return ValidatedUpload(
        filename=filename,
        media_type=expected_media_type,
        content=content,
        checksum=hashlib.sha256(content).hexdigest(),
    )
