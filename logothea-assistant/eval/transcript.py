"""평가용 콜 세그먼트.

실제 운영에서 세그먼트는 STT 가 문장 단위로 끊어 보낸다. 평가는 같은 단위를 쓰도록 전체 원문 트랜스크립트(발언 단위)를
문장으로 나눠 고정 파일로 둔다. 질문셋의 as_of·정답 근거 번호가 이 파일의 sequence 를 가리키므로, 나누는 규칙을 바꾸면
질문셋도 다시 맞춰야 한다(테스트가 원문과 고정 파일이 같은지 확인한다).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TRANSCRIPT_PATH = REPO_ROOT / "data_pipeline" / "data" / "demo" / "wmt-2026q2-transcript.json"
SEGMENTS_PATH = Path(__file__).resolve().parent / "datasets" / "wmt_q2fy27_segments.json"
CALL_STARTED_AT = "2026-08-20T12:00:00Z"
# 문장 하나를 5초로 둔다. 실제 시각과 다르지만 시점 필터(뉴스 발행 시각)는 콜 시작 기준 상대 위치만 맞으면 된다.
SEGMENT_MS = 5_000

# 마침표·물음표·느낌표 뒤 공백, 그다음이 대문자·숫자·따옴표·$ 일 때만 끊는다. "U.S. comp" 처럼 소문자가 이어지면 끊지 않는다.
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'$])")


@dataclass(frozen=True)
class EvalSegment:
    sequence: int
    start_ms: int
    end_ms: int
    speaker: str
    text: str
    timestamp: int
    is_session_end: bool


def split_sentences(text: str) -> list[str]:
    return [piece.strip() for piece in _SENTENCE_RE.split(text.strip()) if piece.strip()]


def build_segments(transcript: dict, call_started_at: str) -> list[EvalSegment]:
    start_epoch = int(datetime.fromisoformat(call_started_at.replace("Z", "+00:00")).timestamp())
    rows: list[tuple[str, str]] = []
    for turn in transcript["turns"]:
        role = (turn.get("role") or "").strip()
        speaker = (turn.get("speaker") or "").strip()
        label = f"{role} · {speaker}" if role and role != speaker else speaker
        for sentence in split_sentences(turn.get("text") or ""):
            rows.append((label, sentence))
    last = len(rows) - 1
    return [
        EvalSegment(
            sequence=index,
            start_ms=index * SEGMENT_MS,
            end_ms=(index + 1) * SEGMENT_MS - 500,
            speaker=label,
            text=sentence,
            timestamp=start_epoch + index * SEGMENT_MS // 1000,
            is_session_end=index == last,
        )
        for index, (label, sentence) in enumerate(rows)
    ]


def write_segments(path: Path, segments: list[EvalSegment]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(s) for s in segments], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def load_segments(path: Path) -> list[EvalSegment]:
    return [EvalSegment(**row) for row in json.loads(Path(path).read_text(encoding="utf-8"))]
