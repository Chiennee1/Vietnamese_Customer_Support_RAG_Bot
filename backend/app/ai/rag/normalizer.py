import re
import unicodedata

MULTIPLE_SPACES = re.compile(r"[^\S\n]+")
EXCESSIVE_NEWLINES = re.compile(r"\n{3,}")


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(
        MULTIPLE_SPACES.sub(" ", line).rstrip() for line in normalized.splitlines()
    )
    return EXCESSIVE_NEWLINES.sub("\n\n", normalized).strip()


def normalize_for_search(value: str) -> str:
    return normalize_text(value).casefold()
