# 제공 PDF 재검증 — 2026-10-02

## 결론

PDF 원문 처리·저장·전체 청킹·마지막 문장 검색과 실행 차단 계약은 통과했다. 실제 Gemini 번역/QA는 성공한 호출도 있으나, 전체 재실행에서 timeout과 fallback이 재발했다. 따라서 실호출 경로 전체 성공 또는 실시간 사용 안정성을 주장할 수 없다.

문서 테스트 중 발견한 **Gemini 실패 응답 캐싱 오류**를 수정했다. 임시 provider 실패로 생성한 내부 fallback에 표식을 붙이고 캐시에서 제외하여 같은 요청이 provider를 다시 호출하도록 했다. 정상 응답 캐시는 유지한다. 실패→실제 재호출 성공→정상 캐시의 회귀 검증을 포함한 AI 전체 테스트: **312 passed, 1 upstream tokenizer deprecation warning, 31.93 s** (`ai-pdf-fix-20261002.log`). 별도 읽기 전용 코드 검토에서도 이 수정의 중대한 결함은 발견되지 않았다.

## 입력과 재현 경계

- 원본: `C:\DownLoad_main\Q4-FY26-Prepared-Remarks.pdf` (원본 수정/저장소 복사 없음)
- SHA-256: `2821d4ccaae50b40dcd28cd4e766c69c509e73d666e4109d5907c7205a03b700`
- 문서 표기: Micron Technology, FY2026 Q4, 2026-09-30. 10쪽, 추출 문자 25,650개.
- 문서의 주장을 테스트 입력으로 사용했다. 발행처와 수치를 외부 자료로 인증한 것은 아니다.
- 1·7·9·10쪽을 pypdfium2로 렌더링하여 표제, 수치, 마지막 문장을 시각 확인했다. Python3.13 런타임에는 fitz가 없어 renderer_unavailable로 기록되지만, 별도 bundled runtime의 렌더링/검토는 완료했다.
- 준비 발언문이며 실제 analyst Q&A는 없다. speaker turn, 영상 타임스탬프, 이전 분기 발언을 생성하지 않았다. 검색 기준 시각은 테스트용이며 실제 발언 시간이 아니다.
- FastAPI TestClient로 실제 현재 앱 라우트와 서비스를 실행했다. 백엔드 HTTP/JWT/Electron/UI/영상/STT/실마이크 테스트는 아니다.
- 폐기 가능한 로컬 Qdrant를 사용했다. 전체 저장소 청킹/검색은 hash embedding, 별도 실제 Gemini embedding은 매출·capex·마지막 문장 3개(각 768차원)를 대상으로 했다.
- phase1은 heuristic, 가격은 제공하지 않았다. runtime-control DB는 의도적으로 unavailable이며 모든 Redis/주문 발행을 비활성화했다.

## 실제 실행 결과

| 항목 | 관측 결과 |
|---|---|
| PDF 업로드 | 200, 10쪽/25,650자 보존, 26개 문서 청크 저장 및 external vector upsert, 경고 없음 |
| Collector transcript 입력 | 200, 원문 문서 1개 수용, transcript vector 청크 49개 |
| 끝부분 검색 | `We will now open for questions.` 원문 검색 성공 |
| 이전 분기 비교 | 이전 문서가 없으므로 insufficient; 비교 내용 생성하지 않음 |
| 실제 Gemini embedding | 3개 벡터, 모두 768차원 |
| 리포트 | 200, 검색 근거 5개. 첫 실행 요약 지지 0/충돌 0. 동일 PDF 안의 검색 결과이며 독립 팩트체크가 아님 |
| legacy 분석 | 두 전체 실행 모두 HTTP 200이지만 rationale은 `Gemini fallback response`, confidence 0. 실제 모델 분석 성공으로 계산하지 않음 |
| 최종 세션 신호 | HOLD, confidence 0.7765, AI score 73.97, execution_allowed=false, Redis 미시도. heuristic/근거 결과가 결합된 참고 출력이며 거래 검증이 아님 |
| 화자 자동 추출 | PDF 업로드 응답 speakers=[]; 화자 메타데이터 자동 인식은 이 문서로 확인되지 않음 |

### 첫 전체 실행

`pdf-micron-20261002.json` / `.log`:

- 매출 번역과 QA 성공. QA 5.633초: “이번 분기 매출은 542억 달러이며, 전년 대비 379% 증가했습니다.” 7쪽의 정확한 원문 인용을 포함한다.
- capex 번역 unavailable, capex QA 12.006초 timeout. 원문과 근거는 보존됐다.
- 20개 assertion 중 17개 통과. 이 집계에는 legacy 분석의 provider 성공 여부가 없었으므로 분석 성공률로 해석하면 안 된다.

### 실패 집중 재검사와 코드 수정

`pdf-capex-retry-20261002.json`:

- 번역 8.007초 timeout.
- QA 2.117초 후 내부 Gemini fallback을 받아 응답 검증 실패.
- 30초 설정의 같은 QA가 0초에 동일 fallback을 반환했다. 코드 확인 결과 내부 fallback도 정상 결과와 함께 캐시에 저장되고 있었다.
- SDK 원본 오류의 HTTP 코드는 첫 실행에서 보존하지 않았으므로 429/503 등 특정 원인으로 단정하지 않는다.

`pdf-capex-after-fix-20261002.json`:

- 기본 8초 번역 제한에서 **3.498초 성공**: “회계 1분기에 당사는 약 $11.5 billion의 설비투자를 전망하며, 2027 회계연도 상반기 설비투자는 약 $25 billion이 될 것으로 예상합니다.” 번역 API의 숫자/영문 단위 보존 계약을 통과했다.
- 기본 12초 QA 제한에서 **9.977초 성공**: “회계연도 1분기의 설비투자(capex)는 약 115억 달러로 예상되며, 회계연도 2027년 상반기의 설비투자는 약 250억 달러가 될 것으로 전망됩니다.”
- QA 인용: `In fiscal Q1, we project capex of around $11.5 billion and anticipate first-half fiscal 2027 capex to be approximately $25 billion.`
- 이 집중 검사에는 external corpus 조회가 없고 선택된 원문만 사용됐다. 성공을 전체 경로 성공으로 확대 해석하지 않는다.

### 수정 후 전체 경로 재실행

`pdf-micron-after-fix-20261002.json` / `.log`:

- 매출 번역 8.014초 timeout, 매출 QA 12.005초 timeout.
- capex 번역 5.530초 성공, QA 1.046초 invalid_or_unsupported_response.
- legacy 분석 11.563초 fallback. 최종 신호·발행 차단은 정상.
- provider 분석 성공 assertion을 추가한 **21개 중 15개 통과, 6개 실패**. 문서 저장/검색 검증은 모두 통과.
- 캐시 수정은 재시도를 가능하게 하지만 provider 지연/실패를 없애지는 않는다. 성공한 표본만 골라 완료 처리하지 않았다.

## 재현 도구 및 남은 범위

`test_supplied_pdf.py`는 전체 PDF/API 경로, `retry_pdf_capex.py`는 실패한 발췌에 대한 집중 진단이다. 키는 지정한 로컬 env에서 필요한 설정만 읽고 출력하지 않는다. JSON/log/추출 원문/렌더링은 ignored 로컬 증거이며 커밋 대상이 아니다.

테스트 스크립트 최초 실행에서는 module-level app 이후 app을 다시 만들어 로컬 Qdrant lock 충돌이 발생했다. 검증 스크립트가 module-level app을 재사용하도록 수정했으며 이후 업로드와 정상 종료를 확인했다. 제품 Qdrant 오류로 집계하지 않았다.

현재 잔여 범위: 실제 provider 안정성·기본 timeout 내 성공률, PDF 화자 인식, 이전 분기 자료를 포함한 비교, backend/terminal/Linux 실행, 영상→STT→화면. 이번 PDF 결과로 기존 미검증 항목을 완료 처리하지 않았다. 커밋/push/실주문 없음.
