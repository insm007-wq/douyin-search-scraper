# src/search_http.py — Phase 1.7 (status_code=9 우회).
# Douyin 봇 분류기를 통과시키기 위해 8가지 변경:
#   1. version_code 190500 → 190600 (실제 douyin web 빌드와 일치)
#   2. browser_version 122 → 130 (Evil0ctal/MediaCrawler 최신)
#   3. from_group_id 빈 값 → 19자리 (브라우저는 절대 빈 값 안 보냄)
#   4. update_version_code/pc_libra_divert/publish_video_strategy_type/
#      show_live_replay_strategy/need_time_list/time_list_query/
#      from_user_page/locate_query/whale_cut_token 추가
#   5. webid 와 device_id 를 다른 19자리 random 으로 분리
#   6. Referer 를 검색 페이지로 명시 (`/search/<kw>?aid=...&type=general`)
#   7. 쿠키 jar 일원화 — Cookie 헤더 직접 주입 제거
#   8. a_bogus 입력에 path 도 함께 (urlencode quote_plus 표준)
import asyncio
import json
import os
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
from search_remote import fetch_remote_search, is_remote_search_enabled
from constants import SEARCH_API_URL, VERBOSE_DIAG, _FIXED_UA, _TT_TRACE_HEADER_KEYS


# Douyin web 의 검색 endpoint path (a_bogus 입력에 사용)
_SEARCH_API_PATH = "/aweme/v1/web/general/search/single/"

# MediaCrawler 가 사용하는 from_group_id 하드코딩값 — 빈 값보다 봇 의심 줄임.
_DEFAULT_FROM_GROUP_ID = "7378810571505847586"

# Phase 1.11: a_bogus 재부착 — late 2024 부터 Douyin 이 a_bogus 검증 강화했다는 보고
# (조사 보고서). 우리 PoC 에서 a_bogus ON 시 status_code=9 받았으나, 그건 다른 변수
# (잘못된 paramset)가 원인이었을 가능성. Phase 1.7 paramset 정렬 후 재시도.
# 환경변수 DOUYIN_ATTACH_A_BOGUS=0 으로 강제 OFF 가능 (비교 검증용).
_ATTACH_A_BOGUS_ENV = (os.environ.get("DOUYIN_ATTACH_A_BOGUS") or "").strip().lower()
_ATTACH_A_BOGUS = _ATTACH_A_BOGUS_ENV not in ("0", "false", "no", "off")  # 기본 ON

# bootstrap 직후 검색 호출까지 jitter — "사람이 페이지 로딩 후 검색 입력" 패턴 흉내.
# 너무 빠르면 봇 의심, 너무 느리면 ttwid stale.
_POST_BOOTSTRAP_JITTER_SEC = (0.6, 1.5)


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
    """Douyin general search → JSON 반환.

    Phase 4.5: DOUYIN_USE_REMOTE_SEARCH=1 시 Railway Puppeteer 컨텍스트에서 검색 실행
    (byted_acrawler 우회). 미설정 시 액터 직접 호출 (Apify IP — verify_check 가능성).
    """
    # ── Phase 4.5: Railway 검색 프록시 우선 경로 ──────────────────────
    if is_remote_search_enabled():
        try:
            offset_int = int(cursor) if str(cursor).strip().lstrip("-").isdigit() else 0
        except Exception:
            offset_int = 0
        remote = await fetch_remote_search(
            client, actor,
            keyword=keyword,
            offset=offset_int,
            sort_type=sort_type,
            publish_time=publish_time,
            search_id=search_id or "",
        )
        if remote.ok:
            return remote.data
        actor.log.warning(
            f"[fetch] remote search 실패 — fallback to local HTTP "
            f"(reason={remote.error!r})"
        )
        # remote 실패 → 아래 local 호출로 fallback (대부분 verify_check 받겠지만 단서 수집용)

    ua = _FIXED_UA

    if not getattr(client, "_dy_device_id", None):
        client._dy_device_id = generate_device_id()
    device_id = client._dy_device_id

    # webid 는 device_id 와 별개 — MediaCrawler 의 get_web_id() 와 동일 패턴.
    # 같은 세션에서 한 번 생성 후 고정 (페이지네이션마다 변하면 의심 지표).
    if not getattr(client, "_dy_webid", None):
        client._dy_webid = generate_device_id()
    webid = client._dy_webid

    if not hasattr(client, "_dy_verify_fp_by_kw"):
        client._dy_verify_fp_by_kw = {}
    if keyword not in client._dy_verify_fp_by_kw:
        client._dy_verify_fp_by_kw[keyword] = generate_verify_fp()
    verify_fp = client._dy_verify_fp_by_kw[keyword]

    # ttwid bootstrap — douyin.com HTML 호출 안 함
    await _ensure_ttwid(client, ua, actor, impersonate=impersonate, keyword=keyword)
    cookies = _cookie_dict(client)

    # Phase 1.8: bootstrap → 검색 사이 jitter. 사람이 페이지 로딩 후 검색 입력하는 시간.
    jitter = random.uniform(*_POST_BOOTSTRAP_JITTER_SEC)
    await asyncio.sleep(jitter)

    # msToken: 사용자 입력 → jar → fallback random.
    # 우리 session.py 가 jar 에 이미 넣어두지만 사용자 override 우선.
    ms_token = (
        (ms_token_override or "").strip()
        or (cookies.get("msToken") or "").strip()
        or generate_random_ms_token()
    )

    # MediaCrawler / Evil0ctal 최신 코드와 정렬한 검색 파라미터.
    # 모든 키-값을 string 으로 (urlencode 일관성).
    params = {
        # 플랫폼·앱 식별자
        "device_platform": "webapp",
        "aid": "6383",
        "channel": "channel_pc_web",
        "pc_client_type": "1",
        "pc_libra_divert": "Windows",
        "version_code": "190600",
        "version_name": "19.6.0",
        "update_version_code": "170400",
        # 검색 파라미터
        "search_channel": "aweme_general",
        "enable_history": "1",
        "search_source": "normal_search",
        "query_correct_type": "1",
        "is_filter_search": "0",
        "from_group_id": _DEFAULT_FROM_GROUP_ID,
        "offset": str(cursor),
        "count": "15",
        "need_filter_settings": "1",
        "list_type": "multi",
        "from_user_page": "1",
        "locate_query": "false",
        "need_time_list": "1",
        "time_list_query": "0",
        "publish_video_strategy_type": "2",
        "show_live_replay_strategy": "1",
        "whale_cut_token": "",
        "keyword": keyword,
        # 환경 시그너처 — 브라우저 패턴 흉내
        "cookie_enabled": "true",
        "screen_width": "1920",
        "screen_height": "1080",
        "browser_language": "zh-CN",
        "browser_platform": "Win32",
        "browser_name": "Chrome",
        "browser_version": "130.0.0.0",
        "browser_online": "true",
        "engine_name": "Blink",
        "engine_version": "130.0.0.0",
        "os_name": "Windows",
        "os_version": "10",
        "cpu_core_num": "8",
        "device_memory": "8",
        "platform": "PC",
        "downlink": "10",
        "effective_type": "4g",
        "round_trip_time": "0",
        # 식별자
        "verifyFp": verify_fp,
        "fp": verify_fp,
        "msToken": ms_token,
        "device_id": device_id,
        "webid": webid,
    }
    if search_id:
        params["search_id"] = search_id
    if publish_time > 0:
        params["publish_time"] = str(publish_time)
    if sort_type > 0:
        params["sort_type"] = str(sort_type)

    # urlencode 기본(quote_plus) 사용 — 검색 키워드 중 한자/한글 인코딩 일관성을 위해.
    qs = urllib.parse.urlencode(params)

    # Phase 1.8 토글: a_bogus 부착 여부.
    # 기본 OFF (MediaCrawler 패턴) — 9 발생 시 ON 으로 비교 검증 가능.
    a_bogus_dbg = ""
    if _ATTACH_A_BOGUS:
        a_bogus = get_a_bogus(qs, ua, body="")
        full_url = f"{SEARCH_API_URL}?{qs}&a_bogus={urllib.parse.quote(a_bogus, safe='')}"
        a_bogus_dbg = f"attached(prefix={a_bogus[:10]!r})"
    else:
        full_url = f"{SEARCH_API_URL}?{qs}"
        a_bogus_dbg = "skipped(MediaCrawler pattern)"

    # Referer 는 검색 페이지 패턴 — type=general 추가로 검색 트래픽 시그널 강화.
    referer = (
        f"https://www.douyin.com/search/{urllib.parse.quote(keyword)}"
        f"?aid=6383&type=general"
    )
    # Cookie 헤더는 명시하지 않음 — curl_cffi jar 가 자동 첨부.
    # 단일 출처 = ttwid 중복/충돌 위험 제거.
    headers = {
        "User-Agent": ua,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": referer,
        "Origin": "https://www.douyin.com",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Ch-Ua": '"Chromium";v="130", "Not(A:Brand";v="24", "Google Chrome";v="130"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
    }
    actor.log.info(
        f"[fetch:req] keyword={keyword!r} a_bogus={a_bogus_dbg} "
        f"jitter={jitter:.2f}s jar_keys={sorted(cookies.keys())} "
        f"ttwid_len={len((cookies.get('ttwid') or '').strip())} "
        f"ms_len={len(ms_token)} webid={webid[:6]}… device_id={device_id[:6]}…"
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
    # Phase 1.9: status_code=0 + items=0 → soft-block 진단.
    # search_nil_info 의 search_nil_type 가 'verify_check' 면 IP/세션 신뢰도 부족.
    # 전체 search_nil_info + qc + extra 를 dump 해서 어떤 신호가 있는지 확인.
    if status_code == 0 and n_items == 0:
        nil_info = data.get("search_nil_info") or {}
        extra = data.get("extra") or {}
        qc = data.get("qc") or ""
        polling = data.get("polling_time")
        guide = data.get("guide_search_words") or []
        actor.log.warning(
            f"[fetch:soft_block] search_nil_type={nil_info.get('search_nil_type')!r} "
            f"search_nil_item={nil_info.get('search_nil_item')!r} "
            f"is_load_more={nil_info.get('is_load_more')!r} "
            f"qc={qc!r} polling={polling!r} guide_words_n={len(guide)}"
        )
        # 전체 nil_info 본문 (text_ 같은 잘림 필드 노출용)
        try:
            actor.log.info(f"[fetch:nil_info_full] {json.dumps(nil_info, ensure_ascii=False)[:600]}")
        except Exception:
            pass
        try:
            actor.log.info(f"[fetch:extra_full] {json.dumps(extra, ensure_ascii=False)[:300]}")
        except Exception:
            pass
    return data


__all__ = ["fetch_douyin_search"]
_ = random  # Phase 3 retry 에서 사용 예정
