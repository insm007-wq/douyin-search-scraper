# src/search_http.py — Phase 1 슬림 버전.
# `fetch_douyin_search()` 가 a_bogus 서명 + 1회 GET 호출 + JSON 반환만 담당.
# Phase 3 에서 재시도/auth-retry/mstoken_remote 통합.
import json
import random
import time
import urllib.parse
from typing import Any

from apify import Actor

from abogus_signer import get_a_bogus
from generators import generate_device_id, generate_random_ms_token, generate_verify_fp
from session import (
    cookie_dict as _cookie_dict,
    req_kw as _req_kw,
    ensure_ttwid as _ensure_ttwid,
)
from constants import SEARCH_API_URL, VERBOSE_DIAG, _FIXED_UA, _TT_TRACE_HEADER_KEYS


def _body_preview(content: bytes, max_chars: int = 400) -> str:
    if not content:
        return "(empty)"
    chunk = content[: max_chars + 4]
    try:
        s = chunk.decode("utf-8")
    except UnicodeDecodeError:
        return f"<binary first {min(48, len(content))} bytes hex> {content[:48].hex()}"
    s = s[:max_chars].replace("\r\n", "\n")
    if len(s) > max_chars:
        s = s[:max_chars] + "…"
    return repr(s)


def _log_http_response_diag(actor: Actor, label: str, r: Any) -> None:
    if not VERBOSE_DIAG:
        return
    h = r.headers
    url_s = str(r.url)
    qprev = url_s.split("?", 1)[-1][:240] if "?" in url_s else url_s[:240]
    actor.log.info(
        f"[diag:{label}] http={r.status_code} url_len={len(url_s)} "
        f"query_preview={qprev!r} bytes={len(r.content)} "
        f"content_type={h.get('content-type', '')!r} "
        f"content_encoding={h.get('content-encoding', '')!r}"
    )
    for key in _TT_TRACE_HEADER_KEYS:
        v = h.get(key)
        if v:
            actor.log.info(f"[diag:{label}] {key}={v[:120]}{'…' if len(v) > 120 else ''}")
    actor.log.info(f"[diag:{label}] body_preview={_body_preview(r.content)}")


def _response_body_len(resp: Any) -> int:
    try:
        c = getattr(resp, "content", None)
        if c:
            return len(c)
    except Exception:
        pass
    return 0


async def fetch_douyin_search(
    client: Any,
    keyword: str,
    cursor: int | str,
    actor: Actor,
    ms_token_override: str | None = None,
    search_id: str = "",
    sort_type: int = 0,
    publish_time: int = 0,
    region: str = "CN",
    impersonate: str | None = None,
):
    """Douyin general search 1회 호출 → JSON 파싱 결과 반환. Phase 1 — 재시도 없음.

    Returns:
        dict — Douyin 응답 JSON (`{status_code, data, cursor, has_more, ...}`).
        호출 실패 시 빈 dict.
    """
    ua = _FIXED_UA  # a_bogus 서명 입력 UA 와 요청 헤더 UA 가 동일해야 함

    if not getattr(client, "_dy_device_id", None):
        client._dy_device_id = generate_device_id()
    device_id = client._dy_device_id

    if not hasattr(client, "_dy_verify_fp_by_kw"):
        client._dy_verify_fp_by_kw = {}
    if keyword not in client._dy_verify_fp_by_kw:
        client._dy_verify_fp_by_kw[keyword] = generate_verify_fp()
    verify_fp = client._dy_verify_fp_by_kw[keyword]

    # warmup 진행 — 쿠키 jar 채우기
    await _ensure_ttwid(client, ua, actor, impersonate=impersonate, keyword=keyword)
    cookies = _cookie_dict(client)

    # msToken: 사용자 입력 → jar → fallback random. Phase 3 에서 mstoken_remote 통합.
    ms_token = (
        (ms_token_override or "").strip()
        or (cookies.get("msToken") or "").strip()
        or generate_random_ms_token()
    )

    # Douyin general search params (필수만 — webapp_id 등 변종은 잡힐 때 추가).
    # 고정 상수 (입력 미노출): is_filter_search/query_correct_type/search_channel/from_group_id.
    params = {
        "device_platform": "webapp",
        "aid": "6383",
        "channel": "channel_pc_web",
        "search_channel": "aweme_general",
        "enable_history": "1",
        "keyword": keyword,
        "search_source": "normal_search",
        "query_correct_type": "1",
        "is_filter_search": "0",
        "from_group_id": "",
        "offset": str(cursor),
        "count": "10",
        "need_filter_settings": "1",
        "list_type": "single",
        "pc_client_type": "1",
        "version_code": "190500",
        "version_name": "19.5.0",
        "cookie_enabled": "true",
        "screen_width": "1920",
        "screen_height": "1080",
        "browser_language": "zh-CN",
        "browser_platform": "Win32",
        "browser_name": "Chrome",
        "browser_version": "122.0.0.0",
        "browser_online": "true",
        "engine_name": "Blink",
        "engine_version": "122.0.0.0",
        "os_name": "Windows",
        "os_version": "10",
        "cpu_core_num": "8",
        "device_memory": "8",
        "platform": "PC",
        "downlink": "10",
        "effective_type": "4g",
        "round_trip_time": "50",
        "verifyFp": verify_fp,
        "fp": verify_fp,
        "msToken": ms_token,
        "device_id": device_id,
        "webid": (cookies.get("s_v_web_id") or "").strip() or device_id,
    }
    if search_id:
        params["search_id"] = search_id
    if publish_time > 0:
        params["publish_time"] = str(publish_time)
    if sort_type > 0:
        params["sort_type"] = str(sort_type)

    qs = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    a_bogus = get_a_bogus(qs, ua, body="")
    full_url = f"{SEARCH_API_URL}?{qs}&a_bogus={urllib.parse.quote(a_bogus, safe='')}"

    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    headers = {
        "User-Agent": ua,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Cookie": cookie_str,
        "Referer": f"https://www.douyin.com/search/{urllib.parse.quote(keyword)}",
        "Origin": "https://www.douyin.com",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
    }
    if VERBOSE_DIAG:
        actor.log.info(
            f"[diag:run] keyword={keyword!r} cursor={cursor!r} "
            f"a_bogus_prefix={a_bogus[:10]!r} ms_len={len(ms_token)} verifyFp={verify_fp[:20]}…"
        )

    started = time.monotonic()
    try:
        response = await client.get(
            full_url,
            headers=headers,
            **_req_kw(client, timeout=15.0, impersonate=impersonate),
        )
    except Exception as e:
        actor.log.error(f"[fetch] HTTP 호출 실패: {type(e).__name__}: {e}")
        return {}
    elapsed = time.monotonic() - started

    _log_http_response_diag(actor, "search", response)

    body_len = _response_body_len(response)
    if body_len == 0:
        actor.log.warning(
            f"[fetch] 빈 본문 (status={response.status_code} "
            f"clen={response.headers.get('content-length')!r} elapsed={elapsed:.2f}s)"
        )
        return {}

    try:
        data = response.json()
    except json.JSONDecodeError as e:
        actor.log.error(
            f"[fetch] JSON 파싱 실패: {e!s} body_preview={_body_preview(response.content)}"
        )
        return {}

    status_code = data.get("status_code", 0)
    n_items = len(data.get("data") or [])
    actor.log.info(
        f"[fetch] OK status_code={status_code} items={n_items} "
        f"cursor→{data.get('cursor')!r} has_more={data.get('has_more')!r} "
        f"elapsed={elapsed:.2f}s keyword={keyword!r}"
    )
    if status_code != 0:
        actor.log.warning(
            f"[fetch] non-zero status_code={status_code} status_msg={data.get('status_msg')!r}"
        )
    return data


__all__ = ["fetch_douyin_search"]
# 미사용 import 가드 (random/time 은 Phase 3 추가 시 사용 예정 — F401 회피)
_ = random, time
