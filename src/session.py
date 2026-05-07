"""Douyin 세션/쿠키 획득 — Phase 1.6 ttwid bootstrap 버전.

핵심 발견 (Evil0ctal/riboly Apache-2.0 패턴):
  - douyin.com HTML 페이지를 GET 하면 안 됨 (__ac_nonce → captcha trap 발동)
  - 대신 `https://ttwid.bytedance.com/ttwid/union/register/` POST 1회로 ttwid 직접 발급
  - msToken / s_v_web_id 는 로컬 랜덤 생성으로도 검색 API 통과 (서버 검증 약함)

이로써 우리는 douyin.com HTML 페이지에 절대 접근하지 않고 JSON API 만 직타격 가능.
"""
from __future__ import annotations

import asyncio
import json
import random
import string
import time
from typing import Any

from apify import Actor

from generators import generate_random_ms_token, generate_s_v_web_id


CURL_IMPERSONATE = "chrome120"
SEARCH_IMPERSONATE_FALLBACKS = ("chrome120", "chrome124")
_BOOTSTRAP_IMPERSONATE_ORDER = ("chrome124", "chrome120", "safari17_0")

# Evil0ctal 패턴 (Apache-2.0): aid=1768=ixigua, service=www.ixigua.com 의 union flow 로
# `.douyin.com` 에서 사용 가능한 ttwid 를 발급. JS 실행도, douyin.com 방문도 불필요.
_TTWID_REGISTER_URL = "https://ttwid.bytedance.com/ttwid/union/register/"
_TTWID_REGISTER_PAYLOAD = {
    "region": "cn",
    "aid": 1768,
    "needFid": False,
    "service": "www.ixigua.com",
    "migrate_info": {"ticket": "", "source": "node"},
    "cbUrlProtocol": "https",
    "union": True,
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


def _set_douyin_cookie(client: Any, name: str, value: str) -> None:
    """curl_cffi 쿠키 jar 에 .douyin.com 도메인 쿠키 설정. 실패는 조용히 무시."""
    if not value:
        return
    try:
        client.cookies.set(name, value, domain=".douyin.com")
    except Exception:
        # curl_cffi 일부 버전은 domain kwarg 미지원 → fallback
        try:
            client.cookies.set(name, value)
        except Exception:
            pass


async def _fetch_ttwid(client: Any, ua: str, actor: Actor, impersonate: str) -> str:
    """ttwid.bytedance.com 에 POST 한 번 → ttwid 쿠키 추출 후 반환.

    Evil0ctal 코드는 헤더 미설정으로 호출 (httpx defaults). curl_cffi 도 동일하게
    `content=` 직렬화 + Content-Type 미지정으로 호출 가능. UA 와 Referer 만 줘서
    봇 의심 줄임.
    """
    headers = {
        "User-Agent": ua,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        # 인증 endpoint 호출 — Origin 은 ixigua 로 (service=www.ixigua.com 와 일치)
        "Origin": "https://www.ixigua.com",
        "Referer": "https://www.ixigua.com/",
    }
    # 기존 jar 의 ttwid 가 잔여하면 응답 쿠키와 섞일 수 있어 호출 직전 비움.
    try:
        client.cookies.delete("ttwid")
    except Exception:
        pass

    body = json.dumps(_TTWID_REGISTER_PAYLOAD, separators=(",", ":")).encode("utf-8")
    t0 = time.monotonic()
    r = await client.post(
        _TTWID_REGISTER_URL,
        data=body,
        headers=headers,
        **req_kw(client, timeout=15.0, impersonate=impersonate),
    )
    elapsed = time.monotonic() - t0

    set_cookie_hdr = r.headers.get("set-cookie", "") or ""
    sc_names = sorted({
        p.split("=", 1)[0].strip().lower()
        for p in set_cookie_hdr.split(",")
        if "=" in p and len(p.split("=", 1)[0].strip()) < 40
    })

    # curl_cffi 의 cookies 는 jar — get_dict 또는 직접 조회
    ttwid = ""
    try:
        ttwid = (client.cookies.get("ttwid", domain=".bytedance.com") or "").strip()
    except Exception:
        pass
    if not ttwid:
        ck = cookie_dict(client)
        ttwid = (ck.get("ttwid") or "").strip()

    actor.log.info(
        f"[BOOTSTRAP:ttwid] status={r.status_code} bytes={len(r.content or b'')} "
        f"elapsed={elapsed:.2f}s set_cookie_names={sc_names} ttwid_len={len(ttwid)}"
    )
    return ttwid


async def ensure_ttwid(
    client: Any,
    ua: str,
    actor: Actor,
    impersonate: str | None = None,
    keyword: str | None = None,  # 호환용 (Phase 1.6 에서는 사용하지 않음)
) -> dict:
    """ttwid bootstrap + 로컬 쿠키 생성. douyin.com HTML 절대 호출 안 함.

    Returns:
        {cookies, msToken, ttwid, s_v_web_id, impersonate, attempt}
    """
    existing = cookie_dict(client)
    existing_ttwid = (existing.get("ttwid") or "").strip()
    if len(existing_ttwid) >= 10:
        actor.log.info(f"[SESSION] bootstrap_skipped=true (ttwid_len={len(existing_ttwid)})")
        return {
            "cookies": existing,
            "msToken": (existing.get("msToken") or "").strip(),
            "ttwid": existing_ttwid,
            "s_v_web_id": (existing.get("s_v_web_id") or "").strip(),
            "impersonate": impersonate or "",
            "attempt": 0,
        }

    started_at = time.monotonic()
    last_error: Exception | None = None

    for attempt in range(1, 4):
        imp = _BOOTSTRAP_IMPERSONATE_ORDER[
            min(attempt - 1, len(_BOOTSTRAP_IMPERSONATE_ORDER) - 1)
        ]
        actor.log.info(f"[SESSION] bootstrap attempt={attempt}/3 impersonate={imp}")
        try:
            ttwid = await _fetch_ttwid(client, ua, actor, imp)
        except Exception as e:
            last_error = e
            ttwid = ""
            actor.log.warning(
                f"[SESSION] ttwid POST 실패 attempt={attempt} imp={imp}: "
                f"{type(e).__name__}: {e}"
            )

        if ttwid and len(ttwid) >= 10:
            # 도메인 .douyin.com 으로 재바인딩 (검색 호출 시 Cookie 헤더에 포함되도록)
            _set_douyin_cookie(client, "ttwid", ttwid)
            # 로컬 생성 쿠키 — Douyin 서버 검증 약함, 랜덤이면 충분 (Evil0ctal/F2 검증)
            ms_token = generate_random_ms_token(length=107)
            s_v_web_id = generate_s_v_web_id()
            _set_douyin_cookie(client, "msToken", ms_token)
            _set_douyin_cookie(client, "s_v_web_id", s_v_web_id)
            # passport_csrf_token: csrf 검증용. POST 가 아닌 GET 검색에는 불필요.
            # csrf 토큰을 쿠키 jar 에 추가하면 일부 endpoint 가 X-CSRFToken 검증을 요구할 수 있어 미설정.

            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            actor.log.info(
                f"[SESSION] source=bootstrap elapsed_ms={elapsed_ms} attempt={attempt} "
                f"imp={imp} ttwid_len={len(ttwid)} ms_len={len(ms_token)} "
                f"svw_len={len(s_v_web_id)}"
            )
            return {
                "cookies": cookie_dict(client),
                "msToken": ms_token,
                "ttwid": ttwid,
                "s_v_web_id": s_v_web_id,
                "impersonate": imp,
                "attempt": attempt,
            }

        if attempt < 3:
            delay = random.uniform(1.0, 2.0)
            actor.log.warning(f"[SESSION] ttwid 미발급 — {delay:.1f}s 후 재시도")
            await asyncio.sleep(delay)

    raise RuntimeError(
        f"Douyin ttwid bootstrap failed after 3 attempts (last_error={last_error!r})"
    )


# F401 가드 — string 은 Phase 3 csrf 토큰 fallback 에 쓰일 예정 (현재 unused)
_ = string
