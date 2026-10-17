"""candidates.csv 에서 사람이 · LLM 이 거를 만한 크기의 후보 목록을 만든다 (#199 2단계 마무리).

규칙은 모두 집계값만 쓴다. 판단(초보자가 모르는가 등)은 3단계에서 한다.

  - 대명사 · 조동사 · 축약형이 섞인 표현은 뺀다(we're seeing, that's why ...)
  - 여러 단어 표현 안쪽에는 of · on · per · to · in · and · for · the 만 허용한다(cost of sales, return on equity)
  - 업계 단어 기준: 1단어는 일반 영어보다 keyness 배 이상 자주 나와야 한다.
    여러 단어는 PMI 가 기준 이상이고, 단어 중 하나는 1단어 기준을 넘는 업계 단어여야 한다
  - 단수 · 복수는 한 줄로 묶고 더 자주 쓰인 표기를 대표로 둔다(headwind/headwinds)
  - 더 긴 표현 안에서만 쓰이는 짧은 표현은 뺀다(free cash ⊂ free cash flow)
  - 공통: 학습용 회사의 COMMON_SHARE 이상이 쓴 표현
    업종: 한 업종 회사의 SECTOR_SHARE 이상이 쓰고, 전체 평균보다 SECTOR_LIFT 배 이상 그 업종에 몰린 표현
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from extract_candidates import STOPWORDS

DATA_DIR = Path.home() / "earning-whisperer-data" / "glossary-corpus"
UNIGRAM_KEYNESS = 1.0
PMI_MIN = 4.0
COMMON_SHARE = 0.07
SECTOR_SHARE = 0.2
SECTOR_LIFT = 3.0
SUBSUMED_RATIO = 0.8

INNER_ALLOWED = {"of", "on", "per", "to", "in", "and", "for", "the"}
BLOCKED = set(
    """i we you they he she it our your their my me us them is are was were be been being have has had
    do does did will would could should can may might must going get got think know see say just also
    really very lot thing things kind sort maybe actually obviously question questions call thank
    thanks good great nice congratulations morning afternoon hello hi everyone""".split()
)


def num(v):
    try:
        return float(v)
    except ValueError:
        return None


def main():
    rows = list(csv.DictReader(open(DATA_DIR / "candidates.csv", newline="")))
    by_term = {r["term"]: r for r in rows}
    with open(DATA_DIR / "split.csv", newline="") as f:
        n_train = sum(1 for r in csv.DictReader(f) if r["split"] == "train")

    def keyword(t):
        r = by_term.get(t)
        return r is not None and (num(r["keyness"]) or 0) >= UNIGRAM_KEYNESS

    def domain(r):
        parts = r["term"].split()
        if len(parts) == 1:
            return keyword(parts[0])
        return (num(r["pmi"]) or 0) >= PMI_MIN and any(keyword(p) for p in parts)

    def well_formed(term):
        parts = term.split()
        if any("'" in p or p in BLOCKED for p in parts):
            return False
        if len(parts) > 1 and any(p in INNER_ALLOWED for p in (parts[0], parts[-1])):
            return False
        if any(p in STOPWORDS and p not in INNER_ALLOWED for p in parts[1:-1]):
            return False
        return True

    kept = [r for r in rows if well_formed(r["term"]) and domain(r)]

    # 단수 · 복수 묶기
    groups = defaultdict(list)
    for r in kept:
        parts = r["term"].split()
        parts[-1] = parts[-1][:-1] if parts[-1].endswith("s") and len(parts[-1]) > 3 else parts[-1]
        groups[" ".join(parts)].append(r)
    merged = []
    for members in groups.values():
        members.sort(key=lambda r: -int(r["freq"]))
        head = dict(members[0])
        head["variants"] = "|".join(m["term"] for m in members[1:])
        merged.append(head)

    # 더 긴 표현 안에서만 쓰이는 짧은 표현 빼기
    freq = {r["term"]: int(r["freq"]) for r in rows}
    longer = defaultdict(int)
    for t, f in freq.items():
        parts = t.split()
        for n in range(1, len(parts)):
            for i in range(len(parts) - n + 1):
                sub = " ".join(parts[i : i + n])
                longer[sub] = max(longer[sub], f)
    merged = [r for r in merged if longer.get(r["term"], 0) < SUBSUMED_RATIO * int(r["freq"])]

    out = []
    for r in merged:
        share = int(r["companies"]) / n_train
        if share >= COMMON_SHARE:
            r["pool"] = "common"
        elif float(r["top_sector_share"]) >= SECTOR_SHARE and float(r["sector_lift"] or 0) >= SECTOR_LIFT:
            r["pool"] = "sector"
        else:
            continue
        out.append(r)
    out.sort(key=lambda r: (r["pool"], r["top_sector"] if r["pool"] == "sector" else "", -int(r["companies"])))

    fields = ["pool", "term", "variants", "companies", "company_share", "top_sector", "top_sector_share",
              "sector_lift", "keyness", "pmi", "freq"]
    with open(DATA_DIR / "shortlist.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)
    counts = defaultdict(int)
    for r in out:
        counts[r["pool"] if r["pool"] == "common" else r["top_sector"]] += 1
    print(len(out), dict(counts))


if __name__ == "__main__":
    main()
