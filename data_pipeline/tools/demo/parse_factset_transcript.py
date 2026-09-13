"""FactSet CallStreet 교정본 PDF → 구조화 JSON.

``parse_transcript.py`` 는 Benzinga 형식을 다룬다. 이 도구는 발행사 IR 페이지가
직접 올리는 FactSet CallStreet 교정본을 다룬다. 같은 콜이라도 두 형식은 구조가
다르다.

* Benzinga — 짧은 줄이 발화자, 뒤따르는 긴 줄이 발언
* FactSet  — 점선으로 블록이 나뉘고, 블록 머리에 이름 / 직책 / ``Q`` 또는 ``A``
             표시가 오고 그 뒤가 발언. 쪽마다 머리말과 꼬리말이 본문 중간에 끼어든다

출력 형식은 ``parse_transcript.py`` 와 같다 — ``speakers`` / ``turns`` / ``qa_pairs``.
어느 경로로 받은 콜이든 같은 모양으로 쓰기 위해서다.

발화자 직책은 앞머리 참가자 명단에서 먼저 읽는다. 본문 블록에서 직책이 두 줄로
접히는 경우가 있어, 명단을 기준으로 몇 줄까지가 직책인지 판정한다.

원문을 손대지 않는다. 발췌와 선별은 별도 단계에서 한다.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import re
import sys


logger = logging.getLogger("parse-factset-transcript")

#: 블록 구분자. 점이 길게 이어진 줄이다.
SEPARATOR_RE = re.compile(r"^[.…]{10,}$")

#: 쪽마다 반복되는 머리말 · 꼬리말. 본문 문단 중간에도 끼어든다.
BOILERPLATE_RE = re.compile(
    r"^(?:"
    r"\d-\d{3}-FACTSET\s+www\.callstreet\.com"
    r"|Copyright\s+©.*FactSet CallStreet"
    r"|Total Pages:\s*\d+"
    r"|Corrected Transcript"
    r"|\d+"
    r")$"
)

#: 명단과 본문을 가르는 절 제목.
SECTION_MANAGEMENT = "MANAGEMENT DISCUSSION SECTION"
SECTION_QA = "QUESTION AND ANSWER SECTION"
SECTION_CORPORATE = "CORPORATE PARTICIPANTS"
SECTION_OTHER = "OTHER PARTICIPANTS"
SECTION_TITLES = {SECTION_MANAGEMENT, SECTION_QA, SECTION_CORPORATE, SECTION_OTHER}

#: 발언 앞에 오는 질문 · 답변 표시.
TURN_MARKERS = {"Q", "A"}

#: 본문 끝의 면책 문구. 이 줄부터는 발언이 아니다.
DISCLAIMER_LINE = "Disclaimer"

#: 애널리스트 직책에 붙는 표시. parse_transcript.py 와 같은 기준을 쓴다.
ANALYST_MARKERS = ("analyst", "research", "capital", "securities", "bank", "partners")


#: 쪽 첫머리에서 머리말 · 꼬리말을 찾을 때 훑는 줄 수.
PAGE_HEAD_SCAN_LINES = 10

#: 머리말로 인정할 최소 반복 쪽 수.
MIN_HEADER_PAGES = 5


def _page_lines(page: str) -> list[str]:
    return [line.replace(" ", " ").strip() for line in page.split("\n") if line.strip()]


def _header_lines(pages: list[list[str]]) -> set[str]:
    """쪽 머리말 · 꼬리말로 반복되는 줄을 찾는다.

    머리말은 발행사 이름과 콜 제목, 날짜로 이루어져 종목마다 다르다. 고정 목록을
    두는 대신 "쪽 첫머리에 반복해서 나온다" 는 성질로 찾는다.

    반복 횟수만으로 판정하면 안 된다. 발언자 이름과 ``Q`` · ``A`` 표시도 본문에서
    수십 번 반복되기 때문이다. 그래서 쪽 첫머리 구역에 나온 줄만 후보로 센다.
    """
    counts: dict[str, int] = {}
    for lines in pages:
        for line in dict.fromkeys(lines[:PAGE_HEAD_SCAN_LINES]):
            if len(line) <= 60:
                counts[line] = counts.get(line, 0) + 1
    return {
        line
        for line, count in counts.items()
        if count >= MIN_HEADER_PAGES and line not in SECTION_TITLES
    }


def _clean_lines(pages: list[list[str]]) -> list[str]:
    """쪽 첫머리의 머리말 · 꼬리말을 걷어내고 본문 줄만 이어 붙인다.

    머리말은 문단 중간에도 끼어들지만 언제나 쪽 첫머리 구역에 모여 있다. 그래서
    본문 전체에서 지우지 않고 그 구역에서만 지운다 — 같은 문자열이 본문에도
    나오는 경우를 살려 두기 위해서다.
    """
    header_lines = _header_lines(pages)
    cleaned: list[str] = []
    for lines in pages:
        for index, line in enumerate(lines):
            if line == DISCLAIMER_LINE:
                return cleaned
            if index < PAGE_HEAD_SCAN_LINES and (line in header_lines or BOILERPLATE_RE.match(line)):
                continue
            cleaned.append(line)
    return cleaned


def _parse_roster(lines: list[str]) -> dict[str, str]:
    """앞머리 참가자 명단에서 이름 → 직책을 읽는다.

    한 항목은 이름 한 줄과 직책 한 줄 이상이다. 직책이 접히면 앞 줄이 쉼표로
    끝난다 — 그것으로 이어지는 줄인지 판정한다.
    """
    roster: dict[str, str] = {}
    name: str | None = None
    role_parts: list[str] = []

    def flush() -> None:
        if name and role_parts:
            roster[name] = " ".join(role_parts)

    for line in lines:
        if SEPARATOR_RE.match(line):
            continue
        if line in SECTION_TITLES:
            if line in (SECTION_MANAGEMENT, SECTION_QA):
                break
            flush()
            name, role_parts = None, []
            continue
        if role_parts and not role_parts[-1].endswith(","):
            flush()
            name, role_parts = line, []
            continue
        if name is None:
            name = line
            continue
        role_parts.append(line)
    flush()
    return roster


def _split_blocks(lines: list[str]) -> list[tuple[str, list[str]]]:
    """본문을 절 이름과 블록 줄 목록의 쌍으로 나눈다."""
    blocks: list[tuple[str, list[str]]] = []
    section = SECTION_MANAGEMENT
    current: list[str] = []
    started = False
    for line in lines:
        if line in (SECTION_MANAGEMENT, SECTION_QA):
            if current:
                blocks.append((section, current))
            section, current, started = line, [], True
            continue
        if not started:
            continue
        if SEPARATOR_RE.match(line):
            if current:
                blocks.append((section, current))
            current = []
            continue
        current.append(line)
    if current:
        blocks.append((section, current))
    return blocks


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _read_block(block: list[str], roster: dict[str, str]) -> dict | None:
    if not block:
        return None

    first = block[0]
    if first.startswith("Operator:"):
        text = " ".join([first[len("Operator:") :].strip(), *block[1:]]).strip()
        return {"speaker": "Operator", "role": "Operator", "marker": "", "text": text} if text else None

    name = first
    role = roster.get(name, "")
    index = 1
    if role:
        # 직책이 몇 줄에 걸쳐 있는지는 명단의 직책과 맞춰 보고 정한다.
        accumulated = ""
        target = _normalize(role)
        while index < len(block):
            accumulated = f"{accumulated} {block[index]}".strip()
            index += 1
            if _normalize(accumulated) == target:
                break
            if not _normalize(target).startswith(_normalize(accumulated)):
                # 명단과 어긋났다. 직책이 한 줄이었다고 보고 되돌린다.
                index = 2
                break

    marker = ""
    if index < len(block) and block[index] in TURN_MARKERS:
        marker = block[index]
        index += 1

    text = " ".join(block[index:]).strip()
    if not text:
        return None
    return {"speaker": name, "role": role, "marker": marker, "text": text}


def _looks_analyst(role: str) -> bool:
    lowered = role.lower()
    return any(marker in lowered for marker in ANALYST_MARKERS)


def _qa_pairs(turns: list[dict]) -> list[dict]:
    """질문 표시가 붙은 발언과 뒤따르는 답변을 짝짓는다.

    FactSet 은 ``Q`` / ``A`` 표시를 달아 주므로 직책으로 추정하지 않는다.
    한 질문에 여러 경영진이 이어 답하는 경우가 흔해, 다음 질문이 나올 때까지의
    답변을 모두 붙인다.
    """
    pairs: list[dict] = []
    for index, turn in enumerate(turns):
        if turn.get("marker") != "Q":
            continue
        answer_parts: list[str] = []
        responders: list[str] = []
        for follow in turns[index + 1 :]:
            if follow.get("marker") == "Q" or follow["speaker"] == "Operator":
                break
            if follow.get("marker") != "A":
                continue
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


def parse(text: str) -> dict:
    """쪽 구분자(``\f``)로 나뉜 트랜스크립트 원문을 구조화한다."""
    pages = [_page_lines(page) for page in text.split("\f")]
    lines = _clean_lines(pages)
    roster = _parse_roster(lines)

    turns: list[dict] = []
    for section, block in _split_blocks(lines):
        turn = _read_block(block, roster)
        if turn is None:
            continue
        turn["section"] = "qa" if section == SECTION_QA else "prepared"
        turns.append(turn)

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


def extract_pdf_text(path: Path) -> str:
    """PDF 에서 본문을 뽑는다.

    PyMuPDF 를 쓴다. 같은 파일을 pypdf 로 뽑으면 단어 중간에 공백이 들어가는
    경우가 있어("recorded" → "rec orded") 임베딩과 대조 품질을 해친다.
    """
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover - 선택 의존성
        raise SystemExit("PyMuPDF 가 필요합니다: pip install pymupdf") from exc

    with pymupdf.open(path) as document:
        # 쪽 경계를 남긴다. 머리말 · 꼬리말을 쪽 첫머리 구역에서만 지우기 위해서다.
        return "\f".join(page.get_text() for page in document)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, type=Path, help="FactSet 교정본 PDF 또는 추출된 텍스트")
    parser.add_argument("--out", required=True, type=Path, help="구조화 JSON 출력 경로")
    parser.add_argument("--out-text", type=Path, help="정리된 본문 텍스트 출력 경로")
    parser.add_argument("--source-url", help="원문을 받은 주소. JSON 의 source 에 남긴다")
    args = parser.parse_args(argv)

    if args.input.suffix.lower() == ".pdf":
        text = extract_pdf_text(args.input)
    else:
        text = args.input.read_text(encoding="utf-8")

    parsed = parse(text)
    # 시연 데이터는 출처가 확인되어야 한다. 어디서 받은 원문인지를 함께 남긴다.
    parsed["source"] = {
        "format": "factset_callstreet_corrected",
        "input_file": args.input.name,
        "url": args.source_url or "",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.out_text:
        body = "\n\n".join(
            f"{turn['speaker']}, {turn['role']}".rstrip(", ") + "\n" + turn["text"] for turn in parsed["turns"]
        )
        args.out_text.parent.mkdir(parents=True, exist_ok=True)
        args.out_text.write_text(body + "\n", encoding="utf-8")

    total_chars = sum(len(turn["text"]) for turn in parsed["turns"])
    logger.info(
        "발화자 %d명, 발언 %d개, Q&A %d쌍, 본문 %d자",
        len(parsed["speakers"]),
        len(parsed["turns"]),
        len(parsed["qa_pairs"]),
        total_chars,
    )
    for speaker in parsed["speakers"]:
        mark = "질문자" if speaker["is_analyst"] else "경영진"
        logger.info("  [%s] %s — %s", mark, speaker["name"], speaker["role"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
