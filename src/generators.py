"""Douyin 요청에 필요한 식별자/토큰 생성 — 무상태 순수 함수.

TikTok 액터의 generators.py 와 인터페이스 동일. 추가:
  - generate_s_v_web_id() — Douyin 의 s_v_web_id 쿠키 (= verifyFp 와 동치, 도메인만 다름)

세션 초기화(session.py)와 검색 API(search_http.py)에서 호출한다.
"""
from __future__ import annotations

import random
import string


_MS_TOKEN_CHARS = string.ascii_letters + string.digits + "=_"
_VERIFY_FP_CHARS = string.ascii_lowercase + string.digits


def generate_random_ms_token(length: int = 107) -> str:
    """Fallback msToken (길이 기본 107).

    Douyin 도 webmssdk.js 로 동적 생성한 토큰을 선호하지만, mstoken_remote 가 실패할 때
    None 보다는 랜덤 토큰이라도 보내는 편이 status_code 를 받기 쉽다.
    """
    return "".join(random.choices(_MS_TOKEN_CHARS, k=length))


def generate_verify_fp() -> str:
    """verifyFp 토큰 (형식: verify_<16자>) — Douyin/TikTok 공통 패턴.

    Douyin 에서는 s_v_web_id 쿠키 값으로도 그대로 사용 가능 (동치 식별자).
    """
    part = "".join(random.choices(_VERIFY_FP_CHARS, k=16))
    return f"verify_{part}"


def generate_s_v_web_id() -> str:
    """Douyin s_v_web_id 쿠키값 — verifyFp 와 동일 포맷이지만 의미상 분리.

    warmup 단계에서 douyin.com 이 직접 set-cookie 로 내려주지만, 누락 시 클라이언트가
    먼저 생성해 보내도 서버가 echo back 함. 같은 세션 동안 고정 유지가 핵심.
    """
    return generate_verify_fp()


def generate_device_id() -> str:
    """deviceId 생성 — 19자리 숫자 문자열 (TikTok/Douyin 웹 ID 규격 동일).

    세션 수명 동안 고정. a_bogus 서명과 msToken 발급 입력으로 사용.
    """
    return str(random.randint(10**18, 10**19 - 1))
