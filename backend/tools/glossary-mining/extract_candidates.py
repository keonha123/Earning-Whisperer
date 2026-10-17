"""어닝콜 자막에서 용어 사전 후보를 뽑는다 (#199 2단계).

LLM 을 부르지 않는다. 자막 원문은 저장소에 넣지 않고, 이 스크립트가 만드는 집계표만 쓴다.

입력 (저장소 밖, 기본 ~/earning-whisperer-data/glossary-corpus)
  kurry_part-0.parquet  HF kurry/sp500_earnings_transcripts
  ticker_sector.csv     ticker, sector, industry (HF glopardo/sp500-earnings-transcripts 에서 뽑음)

출력 (같은 디렉터리)
  split.csv             회사별 train / holdout 구분. holdout 은 6단계 효과 측정에만 쓴다
  candidates.csv        후보 표현과 집계값

절차
  1. 2023년 이후 콜, 업종이 확인되는 회사만 쓴다. 업종별로 회사 10% 를 holdout 으로 뗀다
  2. 사회자(Operator) 발언을 빼고, 문장 부호에서 끊은 구 안에서만 1~4단어 표현을 센다
     - 앞뒤 단어가 불용어이거나 숫자가 섞인 표현은 세지 않는다
  3. 회사 수(company_df)를 센다. 한 회사가 여러 번 말한 표현이 위로 올라오지 않게 하려는 것이다
     - 3~4단어 표현은 안에 든 2단어 표현이 기준을 넘을 때만 센다(메모리 절약)
  4. 기준을 넘은 표현에 대해 업종별 회사 수와 일반 영어 대비 특이도를 붙인다
     - 1단어: wordfreq 일반 영어 빈도 대비 몇 배 많이 나오는지(keyness)
     - 2단어 이상: 자막 안에서 단어들이 우연보다 얼마나 붙어 다니는지(PMI)
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq
from wordfreq import zipf_frequency

DEFAULT_DIR = Path.home() / "earning-whisperer-data" / "glossary-corpus"
MIN_YEAR = 2023
HOLDOUT_RATIO = 0.1
SEED = 199
MIN_COMPANIES = 5

STOPWORDS = set(
    """a about above after again against all also am an and any are as at be because been before being
    below between both but by can could did do does doing down during each few for from further had has
    have having he her here hers herself him himself his how i if in into is it its itself just let me
    more most my myself no nor not now of off on once only or other our ours ourselves out over own
    same she should so some such than that the their theirs them themselves then there these they
    this those through to too under until up very was we were what when where which while who whom
    why will with would you your yours yourself yourselves yeah okay ok well really think know going
    get got go see say said like lot thing things kind sort way maybe actually obviously certainly
    one two three four five first second third us 's 're 've 'll 'd n't thank thanks please""".split()
)

# 문장 부호 · 괄호에서 구를 끊는다. 하이픈 · & · ' 는 단어 안에 둔다(year-over-year, SG&A).
CLAUSE_SPLIT = re.compile(r"[.,;:!?()\[\]\"—–]+|\s-\s")
TOKEN = re.compile(r"[A-Za-z][A-Za-z&'\-]*[A-Za-z]|[A-Za-z]")


def clauses(text: str):
    for clause in CLAUSE_SPLIT.split(text):
        tokens = [t.lower() for t in TOKEN.findall(clause)]
        if tokens:
            yield tokens


def ngrams(tokens: list[str], n: int):
    for i in range(len(tokens) - n + 1):
        gram = tokens[i : i + n]
        if gram[0] in STOPWORDS or gram[-1] in STOPWORDS:
            continue
        yield " ".join(gram)


def call_text(row) -> str:
    turns = row["structured_content"] or []
    if turns:
        return "\n".join(t["text"] for t in turns if (t.get("speaker") or "").strip().lower() != "operator")
    return row["content"] or ""


def load(data_dir: Path):
    sector = {}
    with open(data_dir / "ticker_sector.csv", newline="") as f:
        for r in csv.DictReader(f):
            sector[r["ticker"]] = (r["sector"], r["industry"])
    table = pq.read_table(
        data_dir / "kurry_part-0.parquet",
        columns=["symbol", "year", "quarter", "content", "structured_content"],
        filters=[("year", ">=", MIN_YEAR)],
    )
    by_company: dict[str, list[str]] = defaultdict(list)
    for row in table.to_pylist():
        if row["symbol"] in sector:
            by_company[row["symbol"]].append(call_text(row))
    return by_company, sector


def split_companies(companies, sector, data_dir: Path):
    rng = random.Random(SEED)
    by_sector = defaultdict(list)
    for c in sorted(companies):
        by_sector[sector[c][0]].append(c)
    holdout = set()
    for members in by_sector.values():
        rng.shuffle(members)
        holdout.update(members[: max(1, round(len(members) * HOLDOUT_RATIO))])
    with open(data_dir / "split.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "sector", "split"])
        for c in sorted(companies):
            w.writerow([c, sector[c][0], "holdout" if c in holdout else "train"])
    return [c for c in companies if c not in holdout]


def count(by_company, train, ns, allowed_bigrams=None):
    freq: Counter[str] = Counter()
    company_df: Counter[str] = Counter()
    for c in train:
        seen = set()
        for text in by_company[c]:
            for tokens in clauses(text):
                for n in ns:
                    for g in ngrams(tokens, n):
                        if allowed_bigrams is not None:
                            parts = g.split()
                            if any(" ".join(parts[i : i + 2]) not in allowed_bigrams for i in range(n - 1)):
                                continue
                        freq[g] += 1
                        seen.add(g)
        company_df.update(seen)
    return freq, company_df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DIR)
    args = ap.parse_args()
    data_dir: Path = args.data_dir

    by_company, sector = load(data_dir)
    train = split_companies(list(by_company), sector, data_dir)
    print(f"companies={len(by_company)} train={len(train)} calls={sum(len(by_company[c]) for c in train)}")

    # 1~2단어는 모두 센다. 2단어에서 나온 기준 통과 목록으로 3~4단어를 거른다.
    freq, company_df = count(by_company, train, (1, 2))
    # 3~4단어 안의 2단어는 불용어로 시작 · 끝날 수 있어(cost of sales 의 "of sales") 따로 센다.
    f34, d34 = count(by_company, train, (3, 4), _inner_bigrams(by_company, train))
    freq.update(f34)
    company_df.update(d34)

    unigram_total = sum(v for g, v in freq.items() if " " not in g)
    survivors = {g for g, d in company_df.items() if d >= MIN_COMPANIES}
    print(f"survivors={len(survivors)}")

    # 업종별 회사 수
    sector_companies = Counter(sector[c][0] for c in train)
    sector_df: dict[str, Counter[str]] = defaultdict(Counter)
    for c in train:
        seen = set()
        for text in by_company[c]:
            for tokens in clauses(text):
                for n in (1, 2, 3, 4):
                    for g in ngrams(tokens, n):
                        if g in survivors:
                            seen.add(g)
        for g in seen:
            sector_df[g][sector[c][0]] += 1

    rows = []
    n_train = len(train)
    for g in survivors:
        parts = g.split()
        f = freq[g]
        corpus_zipf = math.log10(f / unigram_total * 1e9)
        keyness = pmi = ""
        if len(parts) == 1:
            keyness = round(corpus_zipf - zipf_frequency(g, "en"), 2)
        else:
            expected = unigram_total
            for p in parts:
                expected *= max(freq.get(p, 1), 1) / unigram_total
            pmi = round(math.log2(f / expected), 2) if expected > 0 else ""
        rates = {s: sector_df[g][s] / sector_companies[s] for s in sector_companies}
        top_sector = max(rates, key=rates.get)
        overall = company_df[g] / n_train
        rows.append(
            {
                "term": g,
                "n": len(parts),
                "freq": f,
                "companies": company_df[g],
                "company_share": round(overall, 3),
                "sectors": sum(1 for s in sector_companies if sector_df[g][s] > 0),
                "top_sector": top_sector,
                "top_sector_share": round(rates[top_sector], 3),
                "sector_lift": round(rates[top_sector] / overall, 2) if overall else "",
                "keyness": keyness,
                "pmi": pmi,
                "general_zipf": round(zipf_frequency(g, "en"), 2),
            }
        )
    rows.sort(key=lambda r: (-r["companies"], -r["freq"]))
    with open(data_dir / "candidates.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows")


def _inner_bigrams(by_company, train):
    """불용어를 포함한 모든 2단어 중 기준 회사 수를 넘는 것. 3~4단어 계산의 사전 필터로 쓴다."""
    inner: Counter[str] = Counter()
    for c in train:
        seen = set()
        for text in by_company[c]:
            for tokens in clauses(text):
                for i in range(len(tokens) - 1):
                    seen.add(f"{tokens[i]} {tokens[i + 1]}")
        inner.update(seen)
    return {g for g, d in inner.items() if d >= MIN_COMPANIES}


if __name__ == "__main__":
    main()
