"""URL 정렬·호스트·도메인 티어 유틸 — play_addr 후보 순위 계산 (Douyin).

TikTok 액터의 동명 모듈에서 호스트 테이블만 분기. 정렬 키 시그니처는 동일하게 유지해
play_url.py 의 호출부에서 분기 코드 없이 재사용 가능.
"""
from __future__ import annotations


def _hostname_lower(url: str) -> str:
    u = url.strip()
    low = u.lower()
    if not (low.startswith("http://") or low.startswith("https://")):
        return ""
    try:
        rest = u.split("://", 1)[1]
        authority = rest.split("/", 1)[0].split("?", 1)[0]
        if "@" in authority:
            authority = authority.rsplit("@", 1)[-1]
        host = authority
        if host.startswith("["):
            end = host.find("]")
            if end != -1:
                host = host[1:end]
        elif ":" in host:
            host = host.rsplit(":", 1)[0]
        return host.lower()
    except Exception:
        return ""


def _query_tail_len(url: str) -> int:
    u = url.strip()
    i = u.find("?")
    if i < 0:
        return 0
    tail = u[i + 1 :]
    if "#" in tail:
        tail = tail.split("#", 1)[0]
    return len(tail)


def _query_param_count(url: str) -> int:
    u = url.strip()
    i = u.find("?")
    if i < 0:
        return 0
    q = u[i + 1 :]
    if "#" in q:
        q = q.split("#", 1)[0]
    if not q:
        return 0
    return q.count("&") + 1


def _domain_tier_and_prime_rank(h: str) -> tuple[int, int]:
    """Douyin CDN 호스트 우선순위.

    관찰된 douyin play_addr 호스트 (2025 기준):
      - v3-web.douyinvod.com / v6-web.douyinvod.com  (가장 흔함, 안정)
      - v9-dy-o.zjcdn.com / v11-dy.douyinvod.com    (지역 분산)
      - aweme.snssdk.com                            (구형, 폴백)
      - v26-x.douyinvod.com / v95-x.douyinvod.com   (고품질 변종)

    *.douyinvod.com 우선, snssdk 차순위, 그 외 기타 ByteDance CDN 후순위.
    """
    if not h:
        return 30, 2
    if h.endswith(".douyinvod.com"):
        return 0, 2
    if h.endswith(".zjcdn.com") or h.endswith(".bytedance.com"):
        return 1, 2
    if h.endswith(".snssdk.com"):
        return 2, 2
    if h.endswith(".bytecdn.cn") or h.endswith(".byteimg.com"):
        return 3, 2
    return 4, 2


def _douyin_auth_param_score(u: str) -> int:
    """인증 파라미터 밀도(점수만). URL 원문은 변경하지 않음.

    Douyin 은 a_bogus / a_bogus_signature / btag / video_id 등이 흔함.
    """
    ul = u.lower()
    n = 0
    if "a_bogus=" in ul:
        n += 1
    if "btag=" in ul:
        n += 1
    if "video_id=" in ul:
        n += 1
    if "ratio=" in ul:
        n += 1
    if "line=" in ul:
        n += 1
    return n


def _addr_block_sort_key(u: str) -> tuple[int, int, int, int, int, int, int, int, int]:
    """티어 → 변종 → btag → URL·쿼리·인증 밀도 → 포맷."""
    ul = u.lower()
    h = _hostname_lower(u)
    tier, prime_var = _domain_tier_and_prime_rank(h)
    btag_rank = 0 if "btag=" in ul else 1
    ln = len(u)
    q = _query_tail_len(u)
    auth = _douyin_auth_param_score(u)
    npar = _query_param_count(u)
    m3u8 = 1 if ".m3u8" in ul else 0
    mp4ish = 0 if (".mp4" in ul or "/video/tos/" in ul) else 1
    return (tier, prime_var, btag_rank, -ln, -q, -auth, -npar, m3u8, mp4ish)
