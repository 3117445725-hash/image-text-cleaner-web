from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class MatchResult:
    matched: bool
    matched_keywords: tuple[str, ...]


def parse_keywords(raw: str) -> list[str]:
    parts = re.split(r"[\n,，;；]+", raw)
    seen: set[str] = set()
    result: list[str] = []
    for item in parts:
        keyword = unicodedata.normalize("NFKC", item).strip()
        if keyword and keyword.casefold() not in seen:
            result.append(keyword)
            seen.add(keyword.casefold())
    return result


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]", text))


def match_text(
    text: str,
    keywords: list[str],
    *,
    mode: str = "whole",
    case_sensitive: bool = False,
) -> MatchResult:
    normalized_text = unicodedata.normalize("NFKC", text or "")
    haystack = normalized_text if case_sensitive else normalized_text.casefold()
    hits: list[str] = []

    for keyword in keywords:
        normalized_keyword = unicodedata.normalize("NFKC", keyword)
        needle = normalized_keyword if case_sensitive else normalized_keyword.casefold()
        if not needle:
            continue

        if mode == "substring" or _contains_cjk(needle) or re.search(r"\s", needle):
            matched = needle in haystack
        else:
            pattern = rf"(?<![\w]){re.escape(needle)}(?![\w])"
            matched = re.search(pattern, haystack, flags=re.UNICODE) is not None

        if matched:
            hits.append(keyword)

    return MatchResult(bool(hits), tuple(hits))
