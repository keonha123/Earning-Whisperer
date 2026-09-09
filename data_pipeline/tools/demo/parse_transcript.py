"""Benzinga 어닝콜 트랜스크립트 → 구조화 JSON.

Benzinga 는 트랜스크립트를 "짧은 줄 = 발화자 라벨, 뒤따르는 긴 줄 = 발언" 형태로 낸다.
이 도구는 그 구조를 파싱해 시연에 필요한 세 가지를 한 번에 뽑는다.

* ``speakers``  — 이름과 직책. 발화자 프로필 화면을 실제 데이터로 채운다.
                 (AI Engine 에는 발화자 분석 로직이 없으므로 사전 조사 데이터로 쓴다.)
* ``turns``     — 발언 순서 전체. 시연 스크립트를 여기서 발췌한다.
* ``qa_pairs``  — 애널리스트 질문과 그에 이어진 경영진 답변. 회피 탐지 입력이다.

원문을 손대지 않는다. 발췌와 선별은 별도 단계에서 하고, 이 단계는 구조화만 한다.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import re
import sys


logger = logging.getLogger("parse-transcript")

#: 발화자 라벨로 인정할 최대 길이. 실제 라벨은 "John David Rainey, CFO" 처럼 짧다.
MAX_SPEAKER_LABEL_CHARS = 80

#: 본문이 아니라 머리말/꼬리말인 줄.
SKIP_LINES = {"Summary", "Full Transcript"}

#: 발화자 라벨 판정. "OPERATOR" 또는 "이름, 직책" 형태.
SPEAKER_RE = re.compile(r"^(OPERATOR|[A-Z][A-Za-z.\-' ]+(?:,\s*.+)?)$")

#: 애널리스트 라벨에 붙는 표시.
ANALYST_MARKERS = ("analyst", "research", "capital", "securities", "bank", "partners")


def _is_speaker(line: str) -> bool:
    if len(line) > MAX_SPEAKER_LABEL_CHARS or line in SKIP_LINES:
        return False
    if line.endswith((".", "?", "!")):
        # 문장이다. "Thank you so much." 같은 짧은 발언이 라벨로 오인되는 것을 막는다.
        return False
    return bool(SPEAKER_RE.match(line))


def _split_label(label: str) -> tuple[str, str]:
    if label == "OPERATOR":
        return "Operator", "Operator"
    name, _, role = label.partition(",")
    return name.strip(), role.strip()


def parse(text: str) -> dict:
    lines = [line.strip() for line in text.split("\n") if line.strip()]

    turns: list[dict] = []
    current: dict | None = None
    for line in lines:
        if _is_speaker(line):
            name, role = _split_label(line)
            current = {"speaker": name, "role": role, "text": ""}
            turns.append(current)
            continue
        if current is None:
            # 본문 시작 전의 요약 문단. 버린다.
            continue
        current["text"] = (current["text"] + " " + line).strip()

    turns = [t for t in turns if t["text"]]

    speakers: dict[str, str] = {}
    for turn in turns:
        if turn["speaker"] != "Operator" and turn["speaker"] not in speakers:
            speakers[turn["speaker"]] = turn["role"]

    return {
        "speakers": [
            {"name": name, "role": role, "is_analyst": _looks_analyst(role)}
            for name, role in speakers.items()
        ],
        "turns": turns,
        "qa_pairs": _qa_pairs(turns),
    }


def _looks_analyst(role: str) -> bool:
    lowered = role.lower()
    return any(marker in lowered for marker in ANALYST_MARKERS)


def _qa_pairs(turns: list[dict]) -> list[dict]:
    """애널리스트 발언과 바로 뒤 경영진 답변을 짝짓는다.

    회피 탐지는 질문 하나와 답변 하나를 받는다. 여러 경영진이 이어 답하는 경우가
    흔하므로 다음 애널리스트/오퍼레이터가 나올 때까지의 발언을 모두 답변으로 붙인다.
    """
    pairs: list[dict] = []
    for index, turn in enumerate(turns):
        if turn["speaker"] == "Operator" or not _looks_analyst(turn["role"]):
            continue
        answer_parts: list[str] = []
        responders: list[str] = []
        for follow in turns[index + 1 :]:
            if follow["speaker"] == "Operator" or _looks_analyst(follow["role"]):
                break
            answer_parts.append(follow["text"])
            if follow["speaker"] not in responders:
                responders.append(follow["speaker"])
        if not answer_parts:
            continue
        pairs.append(
            {
                "asker": turn["speaker"],
                "asker_role": turn["role"],
                "question": turn["text"],
                "responders": responders,
                "answer": " ".join(answer_parts),
            }
        )
    return pairs


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, type=Path, help="추출된 트랜스크립트 텍스트")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    parsed = parse(args.input.read_text(encoding="utf-8"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("발화자 %d명, 발언 %d개, Q&A %d쌍", len(parsed["speakers"]), len(parsed["turns"]), len(parsed["qa_pairs"]))
    for speaker in parsed["speakers"]:
        mark = "질문자" if speaker["is_analyst"] else "경영진"
        logger.info("  [%s] %s — %s", mark, speaker["name"], speaker["role"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
