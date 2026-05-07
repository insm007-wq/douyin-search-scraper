"""aweme/raw item 파싱 유틸 — id·해시태그·통계·업로드 시각 등 순수 변환 (Douyin).

TikTok 액터의 동명 모듈에서 거의 그대로. Douyin 응답의 aweme_info 키 구조가 TikTok 과
동일(aweme_id, desc, text_extra, statistics, author 등) — wrapper 차이(`item.aweme_info`
vs `aweme_info` 직접)는 search_pipeline.py 진입부에서 정규화한다.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from url_sorting import _addr_block_sort_key
from play_url import _extract_urls_from_media_value


def _is_flex_char(ch: str) -> bool:
    """문자 단위 유연 매칭 대상: CJK 한자 + 한글 음절. Douyin 도 한국어 검색 가능 → 한글 유지."""
    cp = ord(ch)
    return (0xAC00 <= cp <= 0xD7AF       # Hangul Syllables
            or 0x4E00 <= cp <= 0x9FFF     # CJK Unified
            or 0x3400 <= cp <= 0x4DBF     # CJK Extension A
            or 0x20000 <= cp <= 0x2A6DF   # CJK Extension B
            or 0xF900 <= cp <= 0xFAFF)    # CJK Compatibility


def _keyword_match(aweme: dict, keyword: str) -> list[str]:
    """키워드가 실제 등장한 필드 이름 리스트. 빈 리스트면 매치 실패 → 필터 탈락.

    1차 토큰 AND → 2차 공백 무시 → 3차 CJK/한글 문자 단위 AND. TikTok 액터와 동일 로직.
    Douyin 은 fuzzy match 보다 엄격하지만 keyword/related 필드는 여전히 끼어들 수 있어 필요.
    """
    if not keyword:
        return ["*"]

    def _norm(s: Any) -> str:
        s = unicodedata.normalize("NFKC", str(s or "")).casefold()
        return ''.join(ch for ch in unicodedata.normalize("NFD", s)
                       if unicodedata.category(ch) != 'Mn')

    nkw = _norm(keyword)
    tokens = [t for t in nkw.split() if t]
    if not tokens:
        return ["*"]

    concat_kw = nkw.replace(" ", "")
    relaxed_enabled = len(concat_kw) >= 2

    flex_chars = list({ch for ch in nkw if _is_flex_char(ch)})
    flex_enabled = len(flex_chars) >= 2

    author = aweme.get("author") or {}
    fields = {
        "desc": aweme.get("desc") or "",
        "author_nickname": author.get("nickname") or "",
        "author_unique_id": author.get("unique_id") or author.get("uniqueId") or "",
        "hashtags": " ".join(_hashtags_from_aweme(aweme)),
    }

    matched: list[str] = []
    for name, val in fields.items():
        nval = _norm(val)
        if all(tok in nval for tok in tokens):
            matched.append(name)
            continue
        if relaxed_enabled and concat_kw in nval.replace(" ", ""):
            matched.append(name)
            continue
        if flex_enabled and all(ch in nval for ch in flex_chars):
            matched.append(name)
    return matched


def _aweme_unique_id(raw: dict, aweme: dict, fallback: str) -> str:
    vid = aweme.get("aweme_id") or raw.get("id") or aweme.get("id")
    if vid is not None and str(vid).strip() and str(vid) != "None":
        return str(vid)
    return fallback


def _hashtags_from_aweme(aweme: dict) -> list[str]:
    tags: list[str] = []
    for t in aweme.get("text_extra") or []:
        if isinstance(t, dict):
            name = t.get("hashtag_name")
            if name:
                tags.append(str(name))
    if tags:
        return tags
    desc = aweme.get("desc") or ""
    for m in re.finditer(r"#([^#\s]+)", desc):
        tags.append(m.group(1))
    return tags


def _safe_int(val: Any) -> int:
    try:
        if val is None or val == "":
            return 0
        return int(float(val))
    except (TypeError, ValueError):
        return 0


def _statistics_merged(aweme: dict, raw: dict) -> dict[str, Any]:
    """statistics·stats 변종 병합. Douyin 은 보통 statistics 만 사용하지만 방어적으로 둘 다."""
    merged: dict[str, Any] = {}
    for src in (
        aweme.get("statistics"),
        raw.get("statistics"),
        aweme.get("stats"),
        raw.get("stats"),
    ):
        if isinstance(src, dict):
            merged.update(src)
    return merged


def _stat_int(st: dict[str, Any], *keys: str) -> int:
    for k in keys:
        if k in st and st[k] is not None:
            return _safe_int(st[k])
    return 0


def _first_url_from_named_keys(obj: Any, keys: tuple[str, ...]) -> str | None:
    if not isinstance(obj, dict):
        return None
    for k in keys:
        if k not in obj:
            continue
        urls = _extract_urls_from_media_value(obj.get(k))
        if urls:
            return sorted(urls, key=_addr_block_sort_key)[0]
    return None


def _uploaded_at_seconds(aweme: dict, raw: dict | None = None) -> int:
    """createTime → Unix 초 변환. Douyin 도 create_time (Unix sec) 동일 패턴."""

    CANDIDATE_KEYS = (
        "create_time", "createTime", "createdAt", "created_at",
        "publish_time", "publishTime", "uploaded_at", "uploadedAt",
        "timestamp",
    )

    def from_dict(d: Any) -> int:
        if not isinstance(d, dict):
            return 0
        for k in CANDIDATE_KEYS:
            v = d.get(k)
            if v is None or v == "":
                continue
            try:
                n = int(v)
            except (TypeError, ValueError):
                continue
            if n <= 0:
                continue
            return n // 1000 if n > 10_000_000_000 else n
        return 0

    n = from_dict(aweme)
    if n:
        return n
    n = from_dict(raw) if raw is not None else 0
    if n:
        return n
    if isinstance(aweme, dict):
        for v in aweme.values():
            if isinstance(v, dict):
                n = from_dict(v)
                if n:
                    return n
    return 0
