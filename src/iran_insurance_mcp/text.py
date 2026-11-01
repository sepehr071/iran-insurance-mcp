"""Small text helpers shared by the tool modules."""

import html
import re

# Code points: Arabic yeh (0x64A) and kaf (0x643) -> Persian forms; drop the zero-width non-joiner (0x200C).
_FOLD = {0x64A: 0x6CC, 0x643: 0x6A9, 0x200C: None}


def norm(s: str) -> str:
    """Lowercase and fold Arabic letter forms, ZWNJ and spaces so Persian queries match loosely."""
    return re.sub(r"\s+", "", s.translate(_FOLD)).lower()


def plain(s: str | None, limit: int = 0) -> str:
    """HTML to plain text; `limit` > 0 cuts it with '...'."""
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()
    return t[:limit].rstrip() + "..." if limit and len(t) > limit else t
