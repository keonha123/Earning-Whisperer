# 어닝콜 Q&A 평가 하네스

logothea-assistant 의 답변 품질을 같은 질문셋으로 반복 측정하는 도구입니다. 모델·프롬프트·검색 방식을 바꿨을 때 좋아졌는지 나빠졌는지를 숫자로 비교하는 것이 목적입니다.

## 측정 지표

- 상태 정확도: 기대 상태(answered, refused, no_evidence)와 실제 상태의 일치율. 적절한 거절과 부적절한 거절을 나누어 셉니다.
- 정답 요점 충족률: 문항별 정답 요점을 LLM 이 present, contradicted, absent 로 판정합니다. 점수 척도는 쓰지 않고 요점별 예/아니오만 봅니다.
- 근거 재현율: 정답 근거 세그먼트 중 답변이 인용한 비율입니다.
- 인용 정밀도: 인용한 근거가 해당 주장을 실제로 뒷받침하는 비율입니다(LLM 판정).
- 수치 검증 통과율: 답변의 수치가 원문 세그먼트에서 확인되는 비율입니다.
- 시점 위반: 질문 시점(as_of) 이후의 세그먼트나 뉴스를 근거로 쓴 건수입니다. 0이어야 하며 보고서 맨 위에 둡니다.
- 지연: 첫 토큰과 완료 시간의 p50, p95.
- 질문당 비용: usage 로 계산한 값입니다.

## 구성

| 파일 | 역할 |
|---|---|
| `transcript.py` | WMT 콜 원문을 문장 단위 세그먼트로 나누고 고정 파일로 저장합니다. |
| `datasets/wmt_q2fy27_segments.json` | 고정 세그먼트. 질문셋의 sequence 가 이 파일을 가리킵니다. |
| `datasets/wmt_q2fy27.json` | 질문셋 60문항(묶음별 구성은 `dataset.py` 의 하한 참고). |
| `dataset.py` | 질문셋 모델과 검증기. |
| `seed.py` | backend 내부 인입 API 로 세그먼트를 적재합니다. 실행마다 새 call_id 를 씁니다. |
| `runner.py` | 문항마다 assistant 에 질문을 보내 SSE 응답을 모읍니다. |
| `metrics.py` | 코드로 계산하는 지표와 요약. |
| `judge.py` | 요점 충족과 인용 정밀도를 LLM 으로 채점합니다. |
| `report.py` | JSON, Markdown 보고서 작성. |
| `__main__.py` | CLI. |

## 실행 전제

로컬 스택이 모두 떠 있어야 합니다. Redis, MySQL, ai-engine, backend, logothea-assistant(기본 `http://127.0.0.1:8100`, `EVAL_ASSISTANT_URL` 로 변경)입니다.

- backend 는 팩트체크·요약·번역을 끈 상태로 띄웁니다. 세그먼트 적재가 Gemini 호출을 일으키지 않게 하기 위함입니다.

  ```
  AI_ENGINE_FACT_CHECK_ENABLED=false AI_ENGINE_SUMMARY_ENABLED=false AI_ENGINE_TRANSLATION_ENABLED=false
  ```

- `logothea-assistant/.env` 에 `OPENAI_API_KEY` 와 `INTERNAL_SECRET` 이 있어야 합니다. backend 의 내부 인입 비밀값과 같은 값이어야 합니다.
- 채점 모델은 기본 `gpt-5.4-mini` 이며 `EVAL_JUDGE_MODEL` 로 바꿉니다. 생성 모델과 다르게 두어 자기 채점 편향을 줄입니다.

## 명령

`logothea-assistant` 디렉터리에서 실행합니다.

```
.venv/bin/python -m eval segments   # 원문에서 고정 세그먼트 파일을 다시 만듭니다.
.venv/bin/python -m eval validate   # 질문셋 검증. 네트워크를 쓰지 않습니다.
.venv/bin/python -m eval run --label baseline            # 예상 비용만 출력하고 종료(코드 2)
.venv/bin/python -m eval run --label baseline --yes      # 실제 실행
```

`run` 옵션은 다음과 같습니다.

- `--yes`: 없으면 예상 비용만 출력하고 아무 요청도 보내지 않습니다.
- `--judge`: LLM 채점을 함께 수행합니다.
- `--runs N`: N회 반복합니다. 회차마다 새 call_id 로 적재하고 보고서는 `{label}-run{n}` 으로 나뉩니다.
- `--limit N`, `--group G`: 일부 문항만 실행합니다.

세그먼트 분할 규칙을 바꾸면 질문셋의 sequence 도 다시 맞춰야 합니다. `validate` 로 확인합니다.

## 비용

1회 실행(60문항, 채점 포함)에 약 $0.3 입니다(생성 gpt-6-luna, 채점 gpt-5.4-mini). 뉴스 검색에서 문항당 Gemini 임베딩이 1회 발생합니다. 임베딩은 하루 요청 한도가 있어 반복 실행 시 유의가 필요합니다. 실제 비용은 보고서의 usage 값으로 확인합니다.

## 결과 위치

`eval/reports/{YYYY-MM-DD}-{label}.json` 과 `.md` 로 저장됩니다. JSON 에는 문항별 답변·상태·인용·채점 결과가 들어 있고, Markdown 은 시점 위반, 요약, 묶음별 표, 상태 불일치 순서입니다.

## 한계

- 단일 콜(WMT 2026 2분기)만 다룹니다. 다른 종목·콜로의 일반화는 확인되지 않았습니다.
- 정답과 요점을 설계자가 직접 작성해 편향이 있을 수 있습니다. 표본 10문항은 사람이 확인해야 하며, 채점기와 사람 판정의 일치율도 아직 확인하지 않았습니다.
- 직전 분기 콜의 핵심 문장이 없어 `vs_last_quarter` 유형은 근거 없음 문항으로 둡니다.
- 세그먼트 시각은 문장당 5초로 근사한 값입니다. 시점 필터는 콜 시작 기준 상대 위치만 맞으면 되므로 허용했습니다.
- 데모 데이터의 뉴스 `published_at` 이 약 4시간 앞당겨진 것으로 보입니다(미국 동부 시각이 UTC 로 저장된 것으로 추정). 그래서 콜 이후 기사 일부가 콜 이전처럼 보입니다. 시점 함정 문항은 이 주제를 피해 작성했으며, 뉴스 시점 위반 수치는 이 영향을 감안해 해석해야 합니다.
