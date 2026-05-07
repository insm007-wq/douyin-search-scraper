"""Railway /douyin-session 호출 — Puppeteer 가 발급한 ttwid 등 쿠키 번들 수신.

Phase 4 — HTTP-only ttwid bootstrap (session.py) 가 verify_check soft-block
으로 통과 못 하므로 우회로. Railway 의 datacenter IP 평판이 Apify residential
보다 byted_acrawler 에서 신뢰가 높아 진짜 douyin.com 쿠키를 받을 수 있다.

API:
  GET <RAILWAY>/douyin-session?force=0
  Headers: X-API-Key: <DOUYIN_SESSION_API_KEY>
  Response: {ok, sessionCookies: {ttwid, s_v_web_id, msToken, ...}, cacheHit, ...}

환경변수:
  DOUYIN_USE_REMOTE_SESSION=1  → Railway 우선 호출 (실패 시 ttwid.bytedance.com 폴백)
  DOUYIN_SESSION_URL           → endpoint override
  DOUYIN_SESSION_API_KEY       → X-API-Key 값 (Railway 와 동일해야 함)
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

from apify import Actor

from constants import DOUYIN_SESSION_URL


@dataclass
class RemoteSessionResult:
    cookies: dict[str, str]
    cache_hit: bool
    elapsed_ms: int
    error: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.cookies.get("ttwid"))


def _is_enabled() -> bool:
    return os.environ.get("DOUYIN_USE_REMOTE_SESSION", "").strip().lower() in (
        "1", "true", "yes", "on"
    )


async def fetch_remote_session(
    client: Any,
    actor: Actor,
    *,
    force: bool = False,
    timeout: float = 60.0,
) -> RemoteSessionResult:
    """Railway /douyin-session 호출. Puppeteer 콜드 스타트 시 최대 25-30초 소요.

    호출자가 client._dy_proxy 를 set 했어도 Railway 에는 직접 접속 (proxies 미주입).
    Railway 의 자기 egress IP 가 douyin 평판 좋은 IP 여야 의미가 있음.
    """
    api_key = (os.environ.get("DOUYIN_SESSION_API_KEY") or "").strip()
    if not api_key:
        return RemoteSessionResult(
            cookies={},
            cache_hit=False,
            elapsed_ms=0,
            error="DOUYIN_SESSION_API_KEY 미설정",
        )

    url = DOUYIN_SESSION_URL + ("?force=1" if force else "")
    headers = {
        "X-API-Key": api_key,
        "Accept": "application/json",
        "User-Agent": "douyin-search-scraper/1.0 (Apify Actor)",
    }
    started = time.monotonic()
    try:
        # 명시적으로 proxies 미사용 — Railway 는 우리 자체 인프라이지 douyin 차단 IP 회피와 무관.
        # client.get 의 _dy_proxy 가 자동 첨부될 수 있어 별도 kwargs 로 빈 proxies 강제.
        r = await client.get(
            url,
            headers=headers,
            impersonate="chrome120",
            timeout=timeout,
            allow_redirects=True,
            proxies={"http": None, "https": None},
        )
    except Exception as e:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        actor.log.warning(
            f"[REMOTE_SESSION] HTTP 실패 elapsed_ms={elapsed_ms}: {type(e).__name__}: {e}"
        )
        return RemoteSessionResult(
            cookies={},
            cache_hit=False,
            elapsed_ms=elapsed_ms,
            error=f"{type(e).__name__}: {e}",
        )

    elapsed_ms = int((time.monotonic() - started) * 1000)

    if r.status_code != 200:
        body_preview = (r.text or "")[:200]
        actor.log.warning(
            f"[REMOTE_SESSION] non-200 status={r.status_code} "
            f"elapsed_ms={elapsed_ms} body={body_preview!r}"
        )
        return RemoteSessionResult(
            cookies={},
            cache_hit=False,
            elapsed_ms=elapsed_ms,
            error=f"status_{r.status_code}",
        )

    try:
        payload = r.json()
    except json.JSONDecodeError as e:
        actor.log.warning(f"[REMOTE_SESSION] JSON 파싱 실패: {e}")
        return RemoteSessionResult(
            cookies={},
            cache_hit=False,
            elapsed_ms=elapsed_ms,
            error="json_parse_err",
        )

    if not payload.get("ok"):
        actor.log.warning(f"[REMOTE_SESSION] ok=false error={payload.get('error')!r}")
        return RemoteSessionResult(
            cookies={},
            cache_hit=False,
            elapsed_ms=elapsed_ms,
            error=str(payload.get("error") or "remote_not_ok"),
        )

    cookies = payload.get("sessionCookies") or {}
    if not isinstance(cookies, dict):
        cookies = {}
    cache_hit = bool(payload.get("cacheHit"))

    actor.log.info(
        f"[REMOTE_SESSION] ok elapsed_ms={elapsed_ms} cache_hit={cache_hit} "
        f"cookie_count={len(cookies)} keys={sorted(cookies.keys())} "
        f"ttwid_len={len((cookies.get('ttwid') or '').strip())}"
    )

    return RemoteSessionResult(
        cookies=cookies,
        cache_hit=cache_hit,
        elapsed_ms=elapsed_ms,
    )


def is_remote_session_enabled() -> bool:
    """main.py / search_http.py 가 remote 사용 여부 판정 시 호출."""
    return _is_enabled()
