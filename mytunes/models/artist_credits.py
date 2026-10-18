from __future__ import annotations

import re


_ARTIST_CREDIT_SEPARATOR = re.compile(
    r"\s*(?:,|;|&|\+|\s+/\s+|"
    r"\bfeat(?:uring)?\.?(?=\s|$)|"
    r"\bft\.?(?=\s|$)|"
    r"\bwith\b|\band\b|\s+x\s+|\bvs\.?(?=\s|$))\s*",
    re.IGNORECASE,
)


def split_artist_credits(credit: str | None) -> list[str]:
    """Split common multi-artist separators while preserving unspaced slashes."""
    if not credit:
        return []

    artists: list[str] = []
    seen: set[str] = set()
    for name in _ARTIST_CREDIT_SEPARATOR.split(credit):
        name = name.strip()
        key = name.casefold()
        if name and key not in seen:
            artists.append(name)
            seen.add(key)
    return artists
