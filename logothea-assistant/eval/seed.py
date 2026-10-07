"""평가용 세그먼트 적재.

backend 내부 인입 API(api-spec 6.4)로 세그먼트를 넣으면 backend 가 Redis 에 콜 단위로 저장한다(비동기).
같은 call_id 로 다시 넣으면 sequence 역행으로 거부되므로 실행마다 새 call_id 를 쓴다.
주의: backend 의 팩트체크·번역·종합 판단을 끄고 띄워야 적재가 Gemini 호출을 일으키지 않는다.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from eval.transcript import EvalSegment


class SeedError(Exception):
    pass


def new_call_id(prefix: str = "eval-wmt-q2fy27", now: Callable[[], float] = time.time) -> str:
    return f"{prefix}-{int(now())}"


def seed_segments(
    http: httpx.Client,
    *,
    backend_url: str,
    secret: str,
    ticker: str,
    call_id: str,
    segments: list[EvalSegment],
    wait_seconds: float = 10.0,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    base = backend_url.rstrip("/")
    headers = {"X-Internal-Secret": secret}
    for segment in segments:
        response = http.post(f"{base}/api/v1/internal/transcript-segment", headers=headers, json={
            "ticker": ticker, "call_id": call_id, "sequence": segment.sequence, "start_ms": segment.start_ms,
            "end_ms": segment.end_ms, "text": segment.text, "speaker": segment.speaker, "timestamp": segment.timestamp,
            "is_session_end": segment.is_session_end,
        })
        if response.status_code != 202:
            raise SeedError(f"세그먼트 {segment.sequence} 적재 실패: HTTP {response.status_code}")
    # 저장은 비동기라 마지막 세그먼트가 보일 때까지 기다린다.
    last = segments[-1].sequence
    waited = 0.0
    while waited <= wait_seconds:
        response = http.get(f"{base}/api/v1/internal/assistant/calls/{call_id}/segments",
                            params={"until_sequence": last}, headers=headers)
        if response.status_code == 200 and response.json().get("last_sequence") == last:
            return len(segments)
        sleep(0.5)
        waited += 0.5
    raise SeedError(f"{wait_seconds}초 안에 세그먼트 {last} 까지 저장되지 않았습니다")
