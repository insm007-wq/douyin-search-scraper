"""Douyin 세션/쿠키 획득 레이어 — Phase 1 슬림 버전.

Phase 1 책임:
- curl_cffi AsyncSession 위에 프록시/impersonate kwargs 합치기
- 2-step warmup (`/` → `/search/<kw>`) 으로 ttwid·s_v_web_id·odin_tt 쿠키 획득
- 클라이언트가 보낼 s_v_web_id 가 누락되면 자동 생성·주입

Phase 3 에서 풀 버전(KV 캐싱·remote msToken·재시도 로테이션)으로 확장.
"""
from __future__ import annotations

import asyncio
import random
import time
import urllib.parse
from typing import Any

from apify import Actor
from generators import generate_s_v_web_id


CURL_IMPERSONATE = "chrome120"
SEARCH_IMPERSONATE_FALLBACKS = ("chrome120", "chrome131")
_SESSION_INIT_IMPERSONATE_ORDER = ("chrome131", "chrome124", "chrome120", "safari17_0")

# Phase 1 검증 규칙: ttwid 만 필수. msToken/odin_tt 는 Phase 3 에서 강화.
# Douyin 의 ttwid 는 첫 페이지 로드만으로 set-cookie 됨.
_SESSION_INIT_REQUIRED = {
    "ttwid": {"min_len": 10, "max_len": None},
}
_SESSION_INIT_OPTIONAL = {
    "s_v_web_id": {"min_len": 10, "max_len": None},
    "odin_tt": {"min_len": 10, "max_len": None},
    "msToken": {"min_len": 80, "max_len": None},
}


def cookie_dict(client: Any) -> dict[str, str]:
    jar = client.cookies
    if hasattr(jar, "get_dict"):
        return jar.get_dict()
    try:
        return dict(jar.items())
    except Exception:
        return {}


def req_kw(
    client: Any,
    timeout: float = 25.0,
    *,
    impersonate: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    kw: dict[str, Any] = {
        "impersonate": impersonate or CURL_IMPERSONATE,
        "timeout": timeout,
        "allow_redirects": True,
    }
    proxy = getattr(client, "_dy_proxy", None)
    if proxy:
        kw["proxies"] = {"http": proxy, "https": proxy}
    kw.update(extra)
    return kw


def impersonate_try_order(client: Any, keyword: str) -> tuple[str, ...]:
    cache = getattr(client, "_dy_search_imp_by_kw", None)
    preferred: str | None = None
    if isinstance(cache, dict):
        preferred = cache.get(keyword)
    if preferred:
        rest = tuple(x for x in SEARCH_IMPERSONATE_FALLBACKS if x != preferred)
        return (preferred,) + rest
    return SEARCH_IMPERSONATE_FALLBACKS


async def ensure_ttwid(
    client: Any,
    ua: str,
    actor: Actor,
    impersonate: str | None = None,
    keyword: str | None = None,
) -> dict:
    """2-step warmup. Phase 1 은 단순 직렬 흐름 — 락·dedup 없이 호출자가 직렬화.

    Returns:
        {cookies, msToken, ttwid, s_v_web_id, impersonate, attempt}
    """
    def _check() -> tuple[dict, list[str]]:
        ck = cookie_dict(client)
        missing: list[str] = []
        for name, rule in _SESSION_INIT_REQUIRED.items():
            val = (ck.get(name) or "").strip()
            if not val:
                missing.append(name)
                continue
            n = len(val)
            if n < rule["min_len"]:
                missing.append(name)
        return ck, missing

    existing, missing_now = _check()
    if not missing_now:
        actor.log.info("[SESSION] warmup_skipped=true (ttwid 이미 보유)")
        return {
            "cookies": existing,
            "msToken": (existing.get("msToken") or "").strip(),
            "ttwid": existing.get("ttwid", ""),
            "s_v_web_id": existing.get("s_v_web_id", ""),
            "impersonate": impersonate or "",
            "attempt": 0,
        }

    base_headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }
    search_kw = (keyword or "热门").strip() or "热门"
    search_url = f"https://www.douyin.com/search/{urllib.parse.quote(search_kw)}"
    steps = (
        ("https://www.douyin.com/", (0.05, 0.15)),
        (search_url, (0.0, 0.0)),
    )

    started_at = time.monotonic()
    last_error: Exception | None = None
    for attempt in range(1, 4):
        imp = _SESSION_INIT_IMPERSONATE_ORDER[
            min(attempt - 1, len(_SESSION_INIT_IMPERSONATE_ORDER) - 1)
        ]
        actor.log.info(f"[SESSION] warmup attempt={attempt}/3 impersonate={imp}")
        try:
            for step_idx, (url, (lo, hi)) in enumerate(steps, 1):
                t0 = time.monotonic()
                r = await client.get(
                    url,
                    headers=base_headers,
                    **req_kw(client, timeout=20.0, impersonate=imp),
                )
                elapsed = time.monotonic() - t0
                ck_now = cookie_dict(client)
                actor.log.info(
                    f"[SESSION:step{step_idx}] url={url.split('?')[0]} "
                    f"status={r.status_code} bytes={len(r.content or b'')} "
                    f"elapsed={elapsed:.2f}s "
                    f"jar: ttwid={len((ck_now.get('ttwid') or '').strip())} "
                    f"s_v_web_id={len((ck_now.get('s_v_web_id') or '').strip())} "
                    f"odin_tt={len((ck_now.get('odin_tt') or '').strip())} "
                    f"msToken={len((ck_now.get('msToken') or '').strip())}"
                )
                await asyncio.sleep(random.uniform(lo, hi))
            last_error = None
        except Exception as e:
            last_error = e
            actor.log.warning(f"[SESSION] warmup 실패 attempt={attempt} imp={imp}: {type(e).__name__}: {e}")

        cookies, missing = _check()
        if not missing:
            # s_v_web_id 누락 시 클라이언트 측에서 생성·주입 (Douyin 도 echo back 함)
            if not cookies.get("s_v_web_id"):
                gen = generate_s_v_web_id()
                try:
                    client.cookies.set("s_v_web_id", gen, domain=".douyin.com")
                    cookies["s_v_web_id"] = gen
                    actor.log.info(f"[SESSION] s_v_web_id 자동 생성 len={len(gen)}")
                except Exception:
                    pass
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            actor.log.info(
                f"[SESSION] source=warmup elapsed_ms={elapsed_ms} attempt={attempt} imp={imp}"
            )
            return {
                "cookies": cookies,
                "msToken": (cookies.get("msToken") or "").strip(),
                "ttwid": cookies.get("ttwid", ""),
                "s_v_web_id": cookies.get("s_v_web_id", ""),
                "impersonate": imp,
                "attempt": attempt,
            }

        if attempt < 3:
            await asyncio.sleep(random.uniform(1.0, 2.0))
            actor.log.warning(f"[SESSION] missing={missing} → 재시도")

    raise RuntimeError(
        f"Douyin session init failed after 3 attempts (last_error={last_error!r})"
    )
