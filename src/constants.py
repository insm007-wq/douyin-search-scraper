# src/constants.py
# Douyin 액터 공용 상수·환경 토글. TikTok 액터 constants.py 의 직계 분기 — 같은 키 이름·구조
# 유지해 grep diff 시 양쪽 동기화 가능.
import os


def _bool_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


# Douyin general search (multi-tab "综合") — most stable for keyword search.
# 다른 후보: /aweme/v1/web/search/item/?type=1 (video-only). Phase 1 에서는 general 만 사용.
SEARCH_API_URL = "https://www.douyin.com/aweme/v1/web/general/search/single/"

# 로그로 배포본 확인용 — 검색 흐름을 바꾸면 값을 올리세요.
ACTOR_SEARCH_REVISION = "20260507_v1_phase0_mvp"

# Railway proxy_apify 허브의 origin (TikTok 액터와 같은 서비스). /mstoken-douyin
# 엔드포인트 추가는 Phase 4 에서 별도 PR 로 진행. 도메인 변경 시 이 한 곳만 수정.
RAILWAY_BASE_ORIGIN = "https://proxyapify-production-d4c5.up.railway.app"

# 프리뷰용 릴레이 베이스(끝이 `?url=`). `DOUYIN_PREVIEW_PROXY_BASE`로 덮어쓰기.
_DEFAULT_DOUYIN_PREVIEW_PROXY_BASE = f"{RAILWAY_BASE_ORIGIN}/?url="
PROXY_BASE = (
    os.environ.get("DOUYIN_PREVIEW_PROXY_BASE") or _DEFAULT_DOUYIN_PREVIEW_PROXY_BASE
).strip()

# true일 때만 HTTP 단계별·헤더·a_bogus 로그 (기본은 조용히)
VERBOSE_DIAG = _bool_env("DOUYIN_VERBOSE_DIAG")

# true이거나 입력 diagnosePlayUrls 시 previewVideoUrl에 HEAD/Range 프로브
_PLAY_URL_DIAG_ENV = _bool_env("DOUYIN_PLAY_URL_DIAG")

# KV Store 세션 캐싱 — ttwid·s_v_web_id·msToken·device_id 를 런 간에 재사용해 warmup 비용 절감.
# Store 이름은 Douyin 전용 — TikTok 액터의 tiktok-session-shared 와 분리 (쿠키 도메인 다름).
KV_SESSION_STORE_NAME = "douyin-session-shared"
KV_SESSION_KEY = "douyin_session_cache"
# Douyin 의 ttwid 실측 수명은 TikTok 보다 짧은 편 (관찰 ~수시간). 12h 는 TikTok 액터와 동일 유지하되,
# 인증 실패 감지 시 _kv_save_session 이 즉시 KV 레코드를 제거 → 다음 런은 새 세션.
KV_SESSION_TTL_SEC = 12 * 3600

# Apify 로그에서 원인 추적용 (Douyin 헤더·본문 일부)
_TT_TRACE_HEADER_KEYS = (
    "x-tt-logid",
    "x-tt-trace-id",
    "x-tt-pba-trace-id",
    "x-tt-trace-tag",
    "x-tt-request-tag",
    "x-bd-auth",
    "x-ss-dp",
)

# UA 는 abogus 서명 입력으로 들어가므로 요청 시점과 절대 동일해야 함 (불일치 = 검증 실패).
# Chrome/122 는 TikTok 액터와 통일.
_FIXED_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
