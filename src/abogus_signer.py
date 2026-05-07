"""abogus.py(벤더링)에 대한 액터 측 thin wrapper.

- TikTok 액터의 xbogus.get_x_bogus(qs, ua) 와 시그니처 호환되는 get_a_bogus() 제공
- 인스턴스 재사용 — ABogus 객체 1개를 모듈 전역으로 캐싱 (스레드 락으로 직렬화).
  ABogus 객체 생성에는 sm3 init 등 ~수 ms 가 들어 매 요청 신규 생성은 낭비.
- preheat_signer() — 부팅 시 첫 호출 latency 흡수용 (TikTok 의 xbogus 와 같은 패턴)
"""
from __future__ import annotations

import threading

from abogus import ABogus, BrowserFingerprintGenerator

# 모듈 전역 캐시. ABogus 인스턴스는 stateful (browser_fp, user_agent) 이라 UA 별로 분리 필요.
_lock = threading.Lock()
_signers: dict[str, ABogus] = {}


def _get_signer(user_agent: str) -> ABogus:
    """UA 별 ABogus 싱글톤 — fp 는 인스턴스마다 생성 후 고정 (세션 동안 동일 fp 유지)."""
    if user_agent not in _signers:
        with _lock:
            if user_agent not in _signers:
                fp = BrowserFingerprintGenerator.generate_fingerprint("Chrome")
                _signers[user_agent] = ABogus(fp=fp, user_agent=user_agent)
    return _signers[user_agent]


def get_a_bogus(query_string: str, user_agent: str, body: str = "") -> str:
    """a_bogus 서명 한 개를 반환.

    Args:
        query_string: URL 쿼리 (예: "device_platform=webapp&aid=6383&...&keyword=foo")
                      a_bogus 자체는 포함하지 않음 — 함수가 추가하지 않고 값만 돌려줌.
        user_agent: HTTP 요청 시 보낼 UA 문자열. 서명 입력에 들어가므로 요청과 정확히 동일해야 함.
        body: POST body. GET 검색 API 는 빈 문자열.

    Returns:
        a_bogus 파라미터 값 (URL-encoded base64 변종, ~165자).
    """
    signer = _get_signer(user_agent)
    # generate_abogus 는 (params_with_abogus, abogus, ua, body) tuple 반환 — 두 번째 원소가 값.
    _, a_bogus, _, _ = signer.generate_abogus(params=query_string, body=body)
    return a_bogus


def preheat_signer(user_agent: str) -> None:
    """첫 get_a_bogus 호출의 ABogus 초기화 비용을 미리 흡수.

    TikTok 의 xbogus.preheat_signer() 와 동일 패턴이지만, Douyin 은 Node 프로세스가 아니라
    파이썬 객체 생성이라 비용이 작음 (~수 ms). 그래도 콜드 스타트의 첫 검색 응답 시간을
    예측 가능하게 만들기 위해 호출 권장.
    """
    try:
        _get_signer(user_agent)
    except Exception:
        # preheat 실패는 치명적이지 않음 — 첫 실제 호출에서 다시 시도.
        pass
