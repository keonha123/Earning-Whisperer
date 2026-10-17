"""검수한 설명(defs/out_*.json)과 기존 사전을 합쳐 glossary_ko.json 새 버전을 만든다 (#199 5단계).

- 기존 항목은 그대로 두고, 공통 후보에서 나온 별칭 중 다른 항목과 겹치지 않는 것만 더한다
- 새 항목은 검수 결정(REVIEW_FIXES)을 적용해 뒤에 붙인다
- 같은 표기가 두 항목에 나오면 멈춘다(백엔드 GlossaryService 와 같은 규칙)
- 파일 형식은 기존처럼 항목 하나를 2~3줄로 쓴다
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

DATA_DIR = Path.home() / "earning-whisperer-data" / "glossary-corpus"
REPO = Path(__file__).resolve().parents[3]
GLOSSARY = REPO / "backend/src/main/resources/data/glossary_ko.json"
VERSION = 3
PARTS = ["0", "1", "2a", "2b", "3a", "3b"]

# 검수에서 고친 것. 별칭 제거는 오탐 · 다른 항목과의 충돌 때문이다.
REMOVE_ALIASES = {
    "reported basis": ["as reported"],          # 일반 문장("as reported by ...")에서도 흔하다
    "lapping": ["lap", "laps"],                 # 일상어 lap 과 겹친다
    "seasonality": ["seasonal"],                # 형용사로 흔히 쓰여 밑줄이 과하게 그어진다
    "book value": ["book value per share"],     # 별도 항목이 있다
    "net debt to EBITDA": ["net leverage ratio"],  # leverage ratio 의 별칭이다
    "customer lifetime value": ["LTV"],         # 부동산 · 대출의 loan-to-value 와 겹친다
}
FIELD_FIXES = {
    "aftermarket": {"category": "metric"},
}
# 기존 항목 중 설명이 비어 있던 것
FILL_EXISTING = {
    "market share": {
        "definition_ko": "어떤 시장 전체의 판매 가운데 한 회사가 차지하는 비율입니다.",
        "why_ko": "시장이 커진 덕에 매출이 늘었는지, 경쟁사 몫을 가져와 늘었는지 구분해 줍니다. 점유율이 올랐다는 말은 경쟁에서 이기고 있다는 설명입니다.",
    },
    "eCommerce": {
        "definition_ko": "인터넷이나 앱으로 상품을 주문하고 사는 온라인 판매입니다. 매장에서 집어 오는 픽업 주문을 포함하는 회사도 있습니다.",
        "why_ko": "전체 매출 가운데 온라인 비중이 얼마나 빨리 커지는지 보면 회사가 소비 방식 변화에 잘 대응하는지 알 수 있습니다. 배송비 부담으로 이익률은 매장 판매보다 낮은 경우가 많습니다.",
    },
}


def load_new():
    out = []
    for p in PARTS:
        for e in json.load(open(DATA_DIR / f"defs/out_{p}.json")):
            if e.get("skip_reason"):
                continue
            e = {k: e[k] for k in ("term", "aliases", "ko", "definition_ko", "why_ko", "category")}
            drop = {a.lower() for a in REMOVE_ALIASES.get(e["term"], [])}
            # 표제어와 대소문자만 다른 별칭 · 중복 별칭도 뺀다. 백엔드는 이것도 같은 표기 중복으로 거부한다.
            seen = {e["term"].lower()}
            aliases = []
            for a in e["aliases"]:
                if a.lower() not in drop and a.lower() not in seen:
                    seen.add(a.lower())
                    aliases.append(a)
            e["aliases"] = aliases
            e.update(FIELD_FIXES.get(e["term"], {}))
            out.append(e)
    return out


def curated_aliases():
    rows = csv.DictReader(open(DATA_DIR / "curated_common.csv", newline=""))
    return {r["canonical"].lower(): [a for a in r["aliases"].split("|") if a] for r in rows}


def dump(glossary: dict) -> str:
    lines = ["{", f'  "version": {glossary["version"]},', '  "terms": [']
    for i, t in enumerate(glossary["terms"]):
        # 분류가 바뀌는 자리에 빈 줄을 둔다(기존 파일 형식)
        if i > 0 and t["category"] != glossary["terms"][i - 1]["category"]:
            lines.append("")
        head = (f'    {{ "term": {json.dumps(t["term"], ensure_ascii=False)}, '
                f'"aliases": {json.dumps(t["aliases"], ensure_ascii=False)}, '
                f'"ko": {json.dumps(t["ko"], ensure_ascii=False)}')
        tail = "," if i < len(glossary["terms"]) - 1 else ""
        if t.get("definition_ko"):
            lines.append(head + ",")
            lines.append(f'      "definition_ko": {json.dumps(t["definition_ko"], ensure_ascii=False)}, '
                         f'"why_ko": {json.dumps(t["why_ko"], ensure_ascii=False)},')
            lines.append(f'      "category": {json.dumps(t["category"])} }}{tail}')
        else:
            lines.append(head + f', "category": {json.dumps(t["category"])} }}{tail}')
    lines += ["  ]", "}"]
    return "\n".join(lines) + "\n"


def main():
    glossary = json.load(open(GLOSSARY))
    owners: dict[str, str] = {}

    def claim(spelling: str, term: str) -> bool:
        key = spelling.lower()
        if key in owners and owners[key] != term:
            return False
        owners[key] = term
        return True

    new = load_new()
    # 새 항목 표기를 먼저 확인해 둔다. 기존 별칭 보강이 새 항목 표기를 가로채지 않게 하기 위해서다.
    reserved = {s.lower() for e in new for s in [e["term"], *e["aliases"]]}

    for t in glossary["terms"]:
        for s in [t["term"], *t["aliases"]]:
            if not claim(s, t["term"]):
                raise SystemExit(f"기존 사전 표기 충돌: {s}")
        t.update(FILL_EXISTING.get(t["term"], {}))

    extra = curated_aliases()
    for t in glossary["terms"]:
        for a in extra.get(t["term"].lower(), []):
            if a.lower() in reserved or a.lower() in owners:
                continue
            claim(a, t["term"])
            t["aliases"].append(a)

    # 새 항목은 분류별로 모아 붙인다. 분류 안 순서는 공통 후보의 회사 수 순서를 따른다.
    order = ["accounting", "capital", "guidance", "metric", "market", "retail", "regulation"]
    new.sort(key=lambda e: order.index(e["category"]))
    for e in new:
        for s in [e["term"], *e["aliases"]]:
            if not claim(s, e["term"]):
                raise SystemExit(f"새 항목 표기 충돌: {s} ({owners[s.lower()]}, {e['term']})")
        glossary["terms"].append(e)

    missing = [t["term"] for t in glossary["terms"] if not (t.get("definition_ko") and t.get("why_ko"))]
    if missing:
        raise SystemExit(f"설명이 빈 항목: {missing}")
    glossary["version"] = VERSION
    GLOSSARY.write_text(dump(glossary), encoding="utf-8")
    print(f"terms={len(glossary['terms'])} new={len(new)}")


if __name__ == "__main__":
    main()
