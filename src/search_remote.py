"""Railway /douyin-search 호출 — Puppeteer 컨텍스트에서 검색 수행 → JSON 수신.

Phase 4.5 — Apify residential/datacenter/cloud-egress 모든 IP 가
byted_acrawler 의 verify_check soft-block 에 막힘. 검색 호출 자체를
Railway Puppeteer 안에서 실행해야 봇 분류기 통과.

API:
  GET <RAILWAY>/douyin-search?keyword=<kw>&offset=<n>&sort_type=<n>&publish_time=<n>&search_id=<sid>
  Headers: X-API-Key: <DOUYIN_SESSION_API_KEY>  (session 과 키 공유)
  Response: {ok, cacheHit, elapsedMs, data: <원본 douyin 응답 JSON>, cookies}

환경변수:
  DOUYIN_USE_REMOTE_SEARCH=1  → search_http.fetch_douyin_search 가 Railway 호출
                                (default: ttwid bootstrap + 액터 직접 호출)
  DOUYIN_SEARCH_URL           → endpoint override
  DOUYIN_SESSION_API_KEY      → /douyin-session 과 동일 키 사용
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

from apify import Actor

from constants import DOUYIN_SEARCH_URL


@dataclass
class RemoteSearchResult:
    data: dict
    cache_hit: bool
    elapsed_ms: int
    error: str | None = None

    @property
    def ok(self) -> bool:
        return not self.error and isinstance(self.data, dict)


def is_remote_search_enabled() -> bool:
    return os.environ.get("DOUYIN_USE_REMOTE_SEARCH", "").strip().lower() in (
        "1", "true", "yes", "on"
    )


async def fetch_remote_search(
    client: Any,
    actor: Actor,
    *,
    keyword: str,
    offset: int = 0,
    sort_type: int = 0,
    publish_time: int = 0,
    search_id: str = "",
    force: bool = False,
    timeout: float = 60.0,
) -> RemoteSearchResult:
    """Railway /douyin-search 호출. Puppeteer 페이지가 살아있으면 빠름 (~2-5초).

    페이지 생성/만료 시 ~20-30초 (콜드 스타트). proxy 우회 — Railway 직접 호출.
    """
    api_key = (os.environ.get("DOUYIN_SESSION_API_KEY") or "").strip()
    if not api_key:
        return RemoteSearchResult(
            data={},
            cache_hit=False,
            elapsed_ms=0,
            error="DOUYIN_SESSION_API_KEY 미설정",
        )

    qs_dict: dict[str, str] = {"keyword": keyword, "offset": str(offset)}
    if sort_type > 0:
        qs_dict["sort_type"] = str(sort_type)
    if publish_time > 0:
        qs_dict["publish_time"] = str(publish_time)
    if search_id:
        qs_dict["search_id"] = search_id
    if force:
        qs_dict["force"] = "1"

    url = f"{DOUYIN_SEARCH_URL}?{urllib.parse.urlencode(qs_dict)}"
    headers = {
        "X-API-Key": api_key,
        "Accept": "application/json",
        "User-Agent": "douyin-search-scraper/1.0 (Apify Actor)",
    }
    started = time.monotonic()
    try:
        r = await client.get(
            url,
            headers=headers,
            impersonate="chrome120",
            timeout=timeout,
            allow_redirects=True,
            proxies={"http": None, "https": None},  # Railway 는 우리 자체 인프라
        )
    except Exception as e:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        actor.log.warning(
            f"[REMOTE_SEARCH] HTTP 실패 elapsed_ms={elapsed_ms}: {type(e).__name__}: {e}"
        )
        return RemoteSearchResult(
            data={},
            cache_hit=False,
            elapsed_ms=elapsed_ms,
            error=f"{type(e).__name__}: {e}",
        )

    elapsed_ms = int((time.monotonic() - started) * 1000)

    if r.status_code != 200:
        body_preview = (r.text or "")[:300]
        actor.log.warning(
            f"[REMOTE_SEARCH] non-200 status={r.status_code} "
            f"elapsed_ms={elapsed_ms} body={body_preview!r}"
        )
        return RemoteSearchResult(
            data={},
            cache_hit=False,
            elapsed_ms=elapsed_ms,
            error=f"status_{r.status_code}",
        )

    try:
        payload = r.json()
    except json.JSONDecodeError as e:
        actor.log.warning(f"[REMOTE_SEARCH] JSON 파싱 실패: {e}")
        return RemoteSearchResult(
            data={},
            cache_hit=False,
            elapsed_ms=elapsed_ms,
            error="json_parse_err",
        )

    if not payload.get("ok"):
        actor.log.warning(f"[REMOTE_SEARCH] ok=false error={payload.get('error')!r}")
        return RemoteSearchResult(
            data={},
            cache_hit=False,
            elapsed_ms=elapsed_ms,
            error=str(payload.get("error") or "remote_not_ok"),
        )

    data = payload.get("data") or {}
    if not isinstance(data, dict):
        data = {}
    cache_hit = bool(payload.get("cacheHit"))
    railway_elapsed = int(payload.get("elapsedMs") or 0)

    n_items = len(data.get("data") or [])
    actor.log.info(
        f"[REMOTE_SEARCH] ok keyword={keyword!r} offset={offset} elapsed_ms={elapsed_ms} "
        f"railway_elapsed_ms={railway_elapsed} cache_hit={cache_hit} "
        f"items={n_items} status_code={data.get('status_code')!r}"
    )

    return RemoteSearchResult(
        data=data,
        cache_hit=cache_hit,
        elapsed_ms=elapsed_ms,
    )
