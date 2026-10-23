"""판정 결과(judge/out_*.csv)를 표제어로 묶고 검수 결정(curation_*.json)을 적용한다 (#199 3단계).

출력 (데이터 디렉터리)
  curated_common.csv   공통 사전 후보
  curated_sector.csv   업종 묶음 후보
열: canonical, aliases(| 구분), category, companies(묶인 표기 중 최대 회사 수), mt_risk, fp_risk, existing
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

DATA_DIR = Path.home() / "earning-whisperer-data" / "glossary-corpus"
HERE = Path(__file__).parent
RISK = "LMH"


def judged_rows():
    for i in range(6):
        ins = list(csv.DictReader(open(DATA_DIR / f"judge/in_{i}.csv", newline="")))
        outs = list(csv.DictReader(open(DATA_DIR / f"judge/out_{i}.csv", newline="")))
        assert len(ins) == len(outs), f"chunk {i}: row count mismatch"
        for a, b in zip(ins, outs):
            assert a["term"] == b["term"], f"chunk {i}: order mismatch at {a['term']}"
            if b["keep"].strip().upper() == "Y" and b["canonical"].strip():
                yield {**a, **b}


def main():
    common_rules = json.load(open(HERE / "curation_common.json"))
    sector_rules = json.load(open(HERE / "curation_sector.json"))
    merge = {k.lower(): v for k, v in {**common_rules["merge"], **sector_rules["merge"]}.items()}
    drop = {t.lower() for rules in (common_rules, sector_rules) for ts in rules["drop"].values() for t in ts}
    to_common = {t.lower() for t in sector_rules["to_common"]}
    category_override = {k.lower(): v for k, v in {**common_rules["category"], **sector_rules["category"]}.items()}

    groups: dict[str, dict] = {}
    cats: dict[str, Counter] = defaultdict(Counter)
    for r in judged_rows():
        name = r["canonical"].strip()
        while name.lower() in merge and merge[name.lower()].lower() != name.lower():
            name = merge[name.lower()]
        key = name.lower()
        if key in drop or r["canonical"].strip().lower() in drop:
            continue
        g = groups.setdefault(key, {"canonical": name, "aliases": set(), "companies": 0, "mt_risk": "L",
                                    "fp_risk": "L", "existing": False})
        own = r["canonical"].strip()
        if own.lower() != key:
            g["aliases"].add(own)
        # 판정 행의 표현이 표제어 그 자체일 때만 그 어형 변화(단수 · 복수)를 별칭으로 둔다.
        # 표제어를 품은 구절("guidance last quarter")을 별칭으로 두면 밑줄이 엉뚱한 범위에 그어진다.
        if r["term"].lower() == own.lower():
            g["aliases"].update(t for t in r["variants"].split("|") if t and t.lower() != key)
        g["companies"] = max(g["companies"], int(r["companies"]))
        g["mt_risk"] = max(g["mt_risk"], r["mt_risk"] or "L", key=RISK.find)
        g["fp_risk"] = max(g["fp_risk"], r["fp_risk"] or "L", key=RISK.find)
        g["existing"] |= "existing" in r["note"]
        cats[key][r["category"]] += 1

    common, sector = [], []
    for key, g in groups.items():
        category = category_override.get(key) or ("common" if key in to_common else cats[key].most_common(1)[0][0])
        row = {**g, "category": category, "aliases": "|".join(sorted(a for a in g["aliases"] if a.lower() != key))}
        (common if category == "common" else sector).append(row)

    fields = ["canonical", "aliases", "category", "companies", "mt_risk", "fp_risk", "existing"]
    for name, rows in (("curated_common.csv", common), ("curated_sector.csv", sector)):
        rows.sort(key=lambda r: (r["category"], -r["companies"]))
        with open(DATA_DIR / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
    print(f"common={len(common)} sector={len(sector)}", dict(Counter(r["category"] for r in sector)))


if __name__ == "__main__":
    main()
