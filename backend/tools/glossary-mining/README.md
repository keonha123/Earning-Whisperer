# 어닝콜 용어 사전 후보 추출 (#199)

`backend/src/main/resources/data/glossary_ko.json` version 3 에 더한 공통 용어를 고른 방법과 결과입니다.
version 2 까지는 월마트 시연 콜을 기준으로 고른 57개였고, version 3 은 여러 업종의 실제 어닝콜 자막에서
회사별 등장 빈도를 세어 176개를 더했습니다.

## 데이터

| 용도 | 데이터 | 라이선스 · 출처 |
|---|---|---|
| 어닝콜 자막 | Hugging Face `kurry/sp500_earnings_transcripts` (33,362콜, 2005–2025) | 카드에 MIT 와 "research and educational use only" 가 함께 적혀 있습니다. 원천은 확인되지 않았습니다 |
| 종목 업종(GICS) | Hugging Face `glopardo/sp500-earnings-transcripts` 의 ticker · sector · industry 열 | 라이선스 표기가 없습니다. 업종 매핑에만 썼습니다 |
| 일반 영어 빈도 | `wordfreq` 3.1.1 | 코드 Apache-2.0, 데이터 CC BY-SA 4.0 |

자막 원문은 저장소에 넣지 않았습니다. 이 디렉터리에는 집계 스크립트와 집계 결과(용어 · 회사 수 · 판정)만 있습니다.
원문은 로컬 `~/earning-whisperer-data/glossary-corpus` 에 받아 두고 씁니다.

## 절차

| 단계 | 스크립트 | 내용 |
|---|---|---|
| 1. 표본 | `extract_candidates.py` | 2023년 이후 콜 중 업종이 확인되는 496개사. 업종별로 회사 10%(50개사)를 효과 측정용으로 떼고, 446개사 · 4,090콜로 집계했습니다 |
| 2. 후보 추출 | `extract_candidates.py` · `shortlist.py` | 사회자 발언을 빼고 1~4단어 표현을 셌습니다. 5개사 이상이 쓴 표현 236,838개를, 일반 영어 대비 특이도(1단어 keyness ≥ 1.0, 여러 단어 PMI ≥ 4.0)와 형태 규칙으로 8,736개까지 줄였습니다. LLM 은 쓰지 않았습니다 |
| 3. 판정 · 검수 | `curate.py` · `curation_common.json` · `curation_sector.json` | 8,736개를 Claude 가 판정 기준(초보자가 모르거나 오해할 만한 전문용어인가, 번역 오류 위험, 오탐 위험)에 따라 1,180행으로 거르고 표제어 753개로 묶었습니다. 이후 사람이 하듯 병합 · 제외 결정을 JSON 으로 남겨 공통 219개(기존 43개 포함), 업종 272개로 정리했습니다 |
| 4. 구조 | `curated_common.csv` · `curated_sector.csv` | 공통 후보는 사전에 넣고, 업종 후보는 이번에 넣지 않고 목록으로만 남겼습니다 |
| 5. 설명 | `build_glossary.py` | 새 공통 용어 176개의 설명을 Claude 가 초안으로 쓰고 검수했습니다. 오탐 · 충돌 별칭을 빼는 결정은 스크립트 안 `REMOVE_ALIASES` 에 있습니다 |
| 6. 효과 측정 | `evaluate.py` | 떼어 둔 50개사의 최근 콜에서 문장 400개를 뽑아, 사전을 보지 않은 판정자가 전문용어를 표시하고 사전 매칭과 비교했습니다 |

판정 · 설명 초안 · 효과 측정 표시에 Gemini 는 쓰지 않았습니다.

## 결과

떼어 둔 50개사 · 문장 400개 · 판정자가 표시한 전문용어 324개 기준입니다.

| | version 2 (57개) | version 3 (233개) |
|---|---|---|
| 커버율 (표시한 전문용어 중 사전이 잡은 비율) | 16.7% (54) | 30.6% (99) |
| 오탐률 (사전 매칭 중 문맥상 용어가 아닌 비율) | 8.8% (6/68) | 7.0% (8/115) |
| 시연 스크립트에서 잡히는 정의 용어 | 19개 | 21개 |

- 오탐은 대부분 뜻이 여럿인 표기입니다. `transactions`(M&A 거래), `comps`(비교 기준), `utilization`(여신 한도 사용률), `DSOs`(치과 서비스 조직)
- 놓친 용어는 업종 용어(gigawatt, business transient, DLC)와 표현 변형(margin expansion, back half, guide)이 많습니다
- 측정 중 "non-operating expenses" 안의 "operating expenses" 가 영업비용으로 잡히는 것을 확인해, 백엔드 `GlossaryTermMatcher` 가 `non-` 바로 뒤에서 용어를 잡지 않도록 바꿨습니다. "low-to-mid single digits" 처럼 범위를 잇는 하이픈 뒤는 그대로 잡습니다

## 업종 후보 (`curated_sector.csv`)

272개를 업종별로 남겼습니다(금융 57, 에너지 43, 유틸리티 37, 헬스케어 26, 부동산 25, 통신 · 미디어 13, 소비재 14,
보험 12, 반도체 11, 소프트웨어 10, 기술 9, 산업재 8, 소매 7). 같은 표기가 업종마다 다른 뜻을 갖는 경우가 있어
(`LTV` 는 부동산 · 대출에서 loan-to-value, `C&I` 는 은행 대출 분류와 유틸리티 고객 분류) 종목 업종에 따라 묶음을
골라 쓰는 구조가 필요합니다. 설명은 아직 쓰지 않았습니다.

## 다시 돌리기

```bash
cd ~/earning-whisperer-data/glossary-corpus
uv venv .venv && uv pip install --python .venv/bin/python pyarrow pandas wordfreq
# kurry_part-0.parquet, glopardo_*.parquet 를 받은 뒤 ticker_sector.csv 를 만든다
T=<repo>/backend/tools/glossary-mining
.venv/bin/python $T/extract_candidates.py
PYTHONPATH=$T .venv/bin/python $T/shortlist.py
# judge/out_*.csv (판정 결과)가 있어야 다음 단계가 돈다
.venv/bin/python $T/curate.py
.venv/bin/python $T/build_glossary.py
.venv/bin/python $T/evaluate.py score
```

판정 결과(`judge/out_*.csv`)와 설명 초안(`defs/out_*.json`), 효과 측정 표시(`eval/*.jsonl`)는 로컬 데이터 디렉터리에
있습니다. 표시 결과에는 자막 문장이 들어 있어 저장소에 넣지 않았습니다.
