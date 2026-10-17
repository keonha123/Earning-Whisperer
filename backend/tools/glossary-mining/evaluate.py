"""사전 효과 측정 (#199 6단계).

holdout 회사(추출에 쓰지 않은 회사)의 콜에서 문장을 뽑아 두 가지를 잰다.

  sample   holdout 문장 표본을 만든다(eval/sample.jsonl). 판정자는 사전을 보지 않고 각 문장의 전문용어를 표시한다
  score    판정 결과(eval/annotated_blind.jsonl, eval/hit_judgments.jsonl)와 사전 매칭을 비교한다
           - 커버율: 판정자가 표시한 전문용어 중 사전 매칭과 겹치는 비율
           - 오탐률: 사전 매칭 중 판정자가 "이 문맥에서는 용어가 아니다" 로 본 비율
  demo     시연 스크립트에서 잡히는 정의 용어 수를 이전 사전과 비교한다

매칭 규칙은 백엔드 GlossaryTermMatcher 와 같다: 대소문자 무시, 단어 경계, 긴 표기 우선, 겹침 없음.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
from pathlib import Path

import pyarrow.parquet as pq

DATA_DIR = Path.home() / "earning-whisperer-data" / "glossary-corpus"
REPO = Path(__file__).resolve().parents[3]
GLOSSARY = REPO / "backend/src/main/resources/data/glossary_ko.json"
SEED = 199
SENTENCES_PER_CALL = 8
SENTENCE = re.compile(r"(?<=[.!?])\s+")


def spellings(glossary: dict, defined_only: bool):
    out = []
    for t in glossary["terms"]:
        if defined_only and not (t.get("definition_ko") and t.get("why_ko")):
            continue
        for s in [t["term"], *t["aliases"]]:
            out.append((s, t["term"]))
    out.sort(key=lambda x: -len(x[0]))
    return [(re.compile(r"(?<![0-9A-Za-z])(?<!\bnon-)" + re.escape(s) + r"(?![0-9A-Za-z])", re.I), term) for s, term in out]


def match(text: str, patterns):
    taken = [False] * len(text)
    hits = []
    for pattern, term in patterns:
        for m in pattern.finditer(text):
            if any(taken[m.start():m.end()]):
                continue
            for i in range(m.start(), m.end()):
                taken[i] = True
            hits.append({"start": m.start(), "end": m.end(), "text": m.group(), "term": term})
    return sorted(hits, key=lambda h: h["start"])


def cmd_sample(_args):
    holdout = {r["ticker"]: r["sector"] for r in csv.DictReader(open(DATA_DIR / "split.csv")) if r["split"] == "holdout"}
    table = pq.read_table(DATA_DIR / "kurry_part-0.parquet", columns=["symbol", "year", "quarter", "structured_content"],
                          filters=[("year", ">=", 2023)])
    latest = {}
    for row in table.to_pylist():
        if row["symbol"] in holdout:
            key = (row["year"], row["quarter"])
            if row["symbol"] not in latest or key > latest[row["symbol"]][0]:
                latest[row["symbol"]] = (key, row["structured_content"])
    rng = random.Random(SEED)
    out = []
    for symbol in sorted(latest):
        turns = [t["text"] for t in latest[symbol][1] if (t.get("speaker") or "").lower() != "operator"]
        sentences = [s.strip() for t in turns for s in SENTENCE.split(t) if 40 <= len(s.strip()) <= 400]
        for i, s in enumerate(rng.sample(sentences, min(SENTENCES_PER_CALL, len(sentences)))):
            out.append({"id": f"{symbol}-{i}", "ticker": symbol, "sector": holdout[symbol], "text": s})
    (DATA_DIR / "eval").mkdir(exist_ok=True)
    with open(DATA_DIR / "eval/sample.jsonl", "w") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"calls={len(latest)} sentences={len(out)}")


def cmd_score(args):
    patterns = spellings(json.load(open(args.glossary or GLOSSARY)), defined_only=True)
    rows = [json.loads(l) for l in open(DATA_DIR / "eval/annotated_blind.jsonl")]
    judged = {}
    if (DATA_DIR / "eval/hit_judgments.jsonl").exists():
        for l in open(DATA_DIR / "eval/hit_judgments.jsonl"):
            r = json.loads(l)
            judged[r["id"]] = {x.lower() for x in r.get("not_terms_in_context", [])}
    gold = covered = matches = false_hits = 0
    missed = []
    for r in rows:
        hits = match(r["text"], patterns)
        spans = [(r["text"].lower().find(j.lower()), j) for j in r["jargon"]]
        for start, j in spans:
            if start < 0:
                continue
            gold += 1
            end = start + len(j)
            if any(h["start"] < end and start < h["end"] for h in hits):
                covered += 1
            else:
                missed.append(j.lower())
        not_terms = judged.get(r["id"], set())
        for h in hits:
            matches += 1
            if h["text"].lower() in not_terms:
                false_hits += 1
    print(f"sentences={len(rows)} jargon={gold} covered={covered} coverage={covered / max(gold, 1):.1%}")
    print(f"matches={matches} false={false_hits} false_rate={false_hits / max(matches, 1):.1%}")
    freq = {}
    for m in missed:
        freq[m] = freq.get(m, 0) + 1
    print("top missed:", sorted(freq.items(), key=lambda x: -x[1])[:40])


def cmd_demo(args):
    script = json.load(open(REPO / "backend/src/main/resources/data/demo-earnings-call.json"))
    text = " ".join(s["text"] for s in script["segments"])
    for label, path in (("before", args.before), ("after", GLOSSARY)):
        if not path:
            continue
        hits = match(text, spellings(json.load(open(path)), defined_only=True))
        print(label, len({h["term"] for h in hits}), sorted({h["term"] for h in hits}))


def cmd_annotate_input(_args):
    """판정자에게 줄 입력. 사전 매칭 결과를 함께 실어 오탐 여부도 같이 판정받는다."""
    patterns = spellings(json.load(open(GLOSSARY)), defined_only=True)
    with open(DATA_DIR / "eval/to_annotate.jsonl", "w") as f:
        for l in open(DATA_DIR / "eval/sample.jsonl"):
            r = json.loads(l)
            r["dictionary_hits"] = sorted({h["text"] for h in match(r["text"], patterns)})
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(required=True)
    sub.add_parser("sample").set_defaults(fn=cmd_sample)
    sub.add_parser("annotate-input").set_defaults(fn=cmd_annotate_input)
    sc = sub.add_parser("score")
    sc.add_argument("--glossary", type=Path)
    sc.set_defaults(fn=cmd_score)
    d = sub.add_parser("demo")
    d.add_argument("--before", type=Path)
    d.set_defaults(fn=cmd_demo)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
