"""play_addr / download_addr / bitrate / 썸네일 URL 후보 추출·정렬 (Douyin).

TikTok 액터의 play_url.py 와 로직 동일 — Douyin 응답 JSON 의 play_addr/download_addr 블록
구조가 TikTok 과 사실상 같기 때문. CDN 호스트 우선순위만 url_sorting.py 에서 분기됨.
"""
from __future__ import annotations

from typing import Any

from url_sorting import _addr_block_sort_key

# 데이터셋에 넣는 재생 URL 후보 개수
PLAY_URL_CANDIDATES_MAX = 12


def _is_http_url(text: str) -> bool:
    t = text.strip().lower()
    return t.startswith("http://") or t.startswith("https://")


def _coerce_media_url(value: Any) -> str | None:
    """play_addr `url_list` 원문 그대로 — urllib.parse·재인코딩·슬라이스·정규식 가공 없음.

    btag·rc·bti 등 쿼리 바이트가 바뀌면 403. str은 API가 준 문자열을 그대로 통과시키고,
    bytes만 UTF-8로 디코드(그 외 변형 없음).
    """
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            s = value.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            s = value.decode("utf-8", errors="replace")
    elif isinstance(value, str):
        s = value
    elif isinstance(value, (int, float)):
        s = str(value)
    else:
        return None
    if not s or not _is_http_url(s):
        return None
    return s


def _urls_from_url_list_item(item: Any) -> list[str]:
    acc: list[str] = []
    if item is None:
        return acc
    if isinstance(item, str):
        u = _coerce_media_url(item)
        if u:
            acc.append(u)
        return acc
    if isinstance(item, (list, tuple)):
        for sub in item:
            acc.extend(_urls_from_url_list_item(sub))
        return acc
    if isinstance(item, dict):
        for k in ("url_list", "urlList", "UrlList"):
            v = item.get(k)
            if isinstance(v, list):
                for sub in v:
                    acc.extend(_urls_from_url_list_item(sub))
                break
        for k in ("url", "Url", "src", "uri", "URI"):
            v = item.get(k)
            if isinstance(v, str):
                u = _coerce_media_url(v)
                if u:
                    acc.append(u)
        for nk in (
            "play_addr",
            "playAddr",
            "PlayAddr",
            "download_addr",
            "downloadAddr",
            "DownloadAddr",
        ):
            sub = item.get(nk)
            if sub is not None:
                acc.extend(_urls_from_addr_block(sub))
        return acc
    return acc


def _url_list_from_block(block: Any) -> list[str]:
    if not isinstance(block, dict):
        return []
    ul = None
    for k in ("url_list", "urlList", "UrlList"):
        v = block.get(k)
        if isinstance(v, list):
            ul = v
            break
    if ul is None:
        return []
    out: list[str] = []
    for u in ul:
        out.extend(_urls_from_url_list_item(u))
    if not out:
        return []
    return sorted(out, key=_addr_block_sort_key)


def _collect_urls_from_addr_dict(d: dict) -> list[str]:
    acc: list[str] = []
    for k in ("url_list", "urlList", "UrlList"):
        v = d.get(k)
        if isinstance(v, list):
            for item in v:
                acc.extend(_urls_from_url_list_item(item))
            break
    for k in ("url", "Url", "src", "uri", "URI"):
        v = d.get(k)
        if isinstance(v, str):
            cu = _coerce_media_url(v)
            if cu:
                acc.append(cu)
    return acc


def _urls_from_addr_block(block: Any) -> list[str]:
    acc: list[str] = []

    if block is None:
        return []
    if isinstance(block, str):
        u = _coerce_media_url(block)
        return [u] if u else []
    if isinstance(block, dict):
        acc.extend(_collect_urls_from_addr_dict(block))
    elif isinstance(block, list):
        for item in block:
            if isinstance(item, dict):
                acc.extend(_collect_urls_from_addr_dict(item))
            else:
                acc.extend(_urls_from_url_list_item(item))

    seen: set[str] = set()
    uniq: list[str] = []
    for s in acc:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    if not uniq:
        return []
    return sorted(uniq, key=_addr_block_sort_key)


_NESTED_ADDR_KEYS = (
    "play_addr",
    "playAddr",
    "PlayAddr",
    "download_addr",
    "downloadAddr",
    "DownloadAddr",
    "play_url",
    "playUrl",
    "download_url",
    "downloadUrl",
    "video_addr",
    "videoAddr",
)


def _dict_media_urls(d: dict) -> list[str]:
    out: list[str] = []
    out.extend(_url_list_from_block(d))
    for k in (
        "url",
        "Url",
        "src",
        "uri",
        "URI",
        "download_addr",
        "downloadAddr",
        "play_addr",
        "playAddr",
        "dynamic_cover",
        "dynamicCover",
        "origin_cover",
        "originCover",
        "cover",
        "Cover",
        "thumb_url",
        "thumbUrl",
        "thumbnail_url",
        "thumbnailUrl",
        "poster",
        "poster_url",
        "posterUrl",
    ):
        u = d.get(k)
        if isinstance(u, str):
            cu = _coerce_media_url(u)
            if cu:
                out.append(cu)
    for nk in _NESTED_ADDR_KEYS:
        sub = d.get(nk)
        if isinstance(sub, dict):
            out.extend(_url_list_from_block(sub))
            for kk in (
                "url",
                "Url",
                "src",
                "uri",
                "URI",
                "download_addr",
                "downloadAddr",
            ):
                u = sub.get(kk)
                if isinstance(u, str):
                    cu = _coerce_media_url(u)
                    if cu:
                        out.append(cu)
        elif isinstance(sub, list):
            for item in sub:
                if isinstance(item, dict):
                    out.extend(_dict_media_urls(item))
                else:
                    out.extend(_urls_from_url_list_item(item))
        elif isinstance(sub, str):
            cu = _coerce_media_url(sub)
            if cu:
                out.append(cu)
    seen: set[str] = set()
    deduped: list[str] = []
    for s in out:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
    return deduped


def _extract_urls_from_media_value(val: Any) -> list[str]:
    out: list[str] = []
    if val is None:
        return out
    if isinstance(val, str):
        u = _coerce_media_url(val)
        return [u] if u else out
    if isinstance(val, dict):
        return _dict_media_urls(val)
    if isinstance(val, (list, tuple)):
        for item in val:
            if isinstance(item, dict):
                out.extend(_dict_media_urls(item))
            else:
                out.extend(_urls_from_url_list_item(item))
        return out
    return out


def _bit_rate_entries(video: dict) -> list[Any]:
    """Douyin video.bit_rate / bitRate / bitrateInfo 등 변종 (TikTok 과 동일 키)."""
    for k in ("bit_rate", "bitRate", "bitrateInfo", "bitrate_info"):
        br = video.get(k)
        if isinstance(br, list) and br:
            return br
    return []


def _bitrate_sort_key(item: Any) -> int:
    if not isinstance(item, dict):
        return 0
    for k in ("BitRate", "bit_rate", "bitrate"):
        v = item.get(k)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    return 0


def _play_url_candidates(video: dict) -> list[str]:
    """재생 URL 후보. play_addr 우선; 정렬은 _addr_block_sort_key (Douyin CDN 호스트 우선)."""
    if not isinstance(video, dict):
        return []
    seen: set[str] = set()
    ordered: list[str] = []

    def extend_tier(raw: list[str]) -> None:
        for u in sorted(raw, key=_addr_block_sort_key):
            if u not in seen:
                seen.add(u)
                ordered.append(u)

    br = _bit_rate_entries(video)
    br_sorted = sorted(br, key=_bitrate_sort_key) if br else []

    tier_a: list[str] = []
    for item in br_sorted:
        if not isinstance(item, dict):
            continue
        for pk in ("play_addr", "playAddr", "PlayAddr"):
            if pk in item:
                tier_a.extend(_urls_from_addr_block(item.get(pk)))
    for pk in ("play_addr", "playAddr", "PlayAddr"):
        if pk in video:
            tier_a.extend(_urls_from_addr_block(video.get(pk)))
    extend_tier(tier_a)

    tier_b_keys = (
        "play_url",
        "playUrl",
        "play_wm_addr",
        "playWmAddr",
        "play_addr_lowbr",
        "playAddrLowbr",
        "playApi",
        "play_api",
    )
    tier_b: list[str] = []
    for k in tier_b_keys:
        if k in video:
            tier_b.extend(_extract_urls_from_media_value(video.get(k)))
    extend_tier(tier_b)

    tier_c: list[str] = []
    for item in br_sorted:
        if not isinstance(item, dict):
            continue
        for dk in ("download_addr", "downloadAddr", "DownloadAddr"):
            if dk in item:
                tier_c.extend(_urls_from_addr_block(item.get(dk)))
    for dk in (
        "download_addr",
        "downloadAddr",
        "DownloadAddr",
        "download_url",
        "downloadUrl",
    ):
        if dk in video:
            tier_c.extend(_urls_from_addr_block(video.get(dk)))
    extend_tier(tier_c)

    tier_d: list[str] = []
    for k in ("video_url", "videoUrl", "video_uri", "videoUri"):
        if k in video:
            tier_d.extend(_extract_urls_from_media_value(video.get(k)))
    extend_tier(tier_d)

    tier_e: list[str] = []
    for item in br_sorted:
        if isinstance(item, dict):
            tier_e.extend(_extract_urls_from_media_value(item))
    extend_tier(tier_e)

    return ordered


def _best_preview_play_url(
    play_urls: list[str],
) -> tuple[str | None, str | None, list[str]]:
    """프리뷰·videoUrl용 URL: HLS가 아닌 직링크 우선(MP4·tos 등), 없으면 정렬 첫 항."""
    if not play_urls:
        return None, None, []
    ul = [u for u in play_urls if u]
    if not ul:
        return None, None, []
    m3u8 = next((u for u in ul if ".m3u8" in u.lower()), None)
    sorted_ul = sorted(ul, key=_addr_block_sort_key)
    primary = next((u for u in sorted_ul if ".m3u8" not in u.lower()), sorted_ul[0])
    candidates = sorted_ul[:PLAY_URL_CANDIDATES_MAX]
    return primary, m3u8, candidates


def _merged_video_block(raw: dict, aweme: dict) -> dict:
    """item.video와 aweme.video를 합쳐 검색 API 필드 분리 대응."""
    av = aweme.get("video") if isinstance(aweme.get("video"), dict) else {}
    rv = raw.get("video") if isinstance(raw.get("video"), dict) else {}
    if not av and not rv:
        return {}
    return {**rv, **av}


def _first_video_play_url(video: dict) -> str | None:
    u = _play_url_candidates(video)
    if not u:
        return None
    primary, _, _ = _best_preview_play_url(u)
    return primary
