# src/main.py — Phase 1 MVP entrypoint.
# 한 키워드 1회 검색해서 첫 3건의 raw item 을 로그에 출력한다.
# Phase 2/3/4 에서 페이지네이션·dataset push·KV 세션·미러링 추가.

import asyncio
import json
import os
import sys

from apify import Actor
from curl_cffi.requests import AsyncSession

from constants import _FIXED_UA, ACTOR_SEARCH_REVISION
from search_http import fetch_douyin_search
from abogus_signer import preheat_signer


async def _run() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}
        keywords = actor_input.get("keywords") or []
        if isinstance(keywords, str):
            keywords = [keywords]
        keyword = (
            (actor_input.get("keyword") or "").strip()
            or (keywords[0].strip() if keywords else "")
            or "热门"
        )
        ms_token_override = (actor_input.get("msToken") or "").strip() or None
        sort_type = int(actor_input.get("sortType", 0) or 0) if str(actor_input.get("sortType", "0")).isdigit() else 0

        Actor.log.info(
            f"[main] revision={ACTOR_SEARCH_REVISION} keyword={keyword!r} "
            f"ms_token_override={'yes' if ms_token_override else 'no'} pid={os.getpid()}"
        )

        # a_bogus 서명자 1회 인스턴스화 (콜드 스타트 latency 흡수)
        preheat_signer(_FIXED_UA)

        async with AsyncSession() as client:
            data = await fetch_douyin_search(
                client,
                keyword=keyword,
                cursor=0,
                actor=Actor,
                ms_token_override=ms_token_override,
                sort_type=sort_type,
            )

        items = data.get("data") or []
        Actor.log.info(f"[main] returned items={len(items)} status_code={data.get('status_code')}")

        # Phase 1 검증: 처음 3건의 핵심 필드만 로그에 dump → API 동작 여부 확인
        for i, raw in enumerate(items[:3]):
            aweme = raw.get("aweme_info") if isinstance(raw, dict) and isinstance(raw.get("aweme_info"), dict) else raw
            if not isinstance(aweme, dict):
                continue
            aid = aweme.get("aweme_id") or aweme.get("id") or "?"
            desc = (aweme.get("desc") or "")[:80]
            author = (aweme.get("author") or {})
            uid = author.get("unique_id") or author.get("nickname") or "?"
            stats = aweme.get("statistics") or {}
            Actor.log.info(
                f"[item {i}] id={aid} author={uid!r} desc={desc!r} "
                f"digg={stats.get('digg_count')} comment={stats.get('comment_count')} "
                f"share={stats.get('share_count')} play={stats.get('play_count')}"
            )

        if not items:
            # 진단: status_code 가 0 이 아니거나 응답 keys 가 비정상이면 dump
            Actor.log.warning(
                f"[main] no items. response_keys={sorted(list(data.keys()))[:20]} "
                f"snippet={json.dumps(data, ensure_ascii=False)[:400]}"
            )


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
