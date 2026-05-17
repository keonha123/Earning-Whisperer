# Data Pipeline 재무제표 수집 문서

## 개요

`data_pipeline`의 재무제표 수집 기능은 yfinance를 통해 기업별 분기 재무제표를 가져와 MySQL의 `financial_statement_items` 테이블에 저장한다.

현재 수집 대상 재무제표는 다음 3종이다.

| statement_type     | yfinance 호출                                | 설명       |
| ------------------ | -------------------------------------------- | ---------- |
| `income_statement` | `Ticker.get_income_stmt(freq="quarterly")`   | 손익계산서 |
| `balance_sheet`    | `Ticker.get_balance_sheet(freq="quarterly")` | 재무상태표 |
| `cash_flow`        | `Ticker.get_cashflow(freq="quarterly")`      | 현금흐름표 |

구현 위치:

| 파일                                                        | 역할                                              |
| ----------------------------------------------------------- | ------------------------------------------------- |
| `data_pipeline/collectors/financial_statements/base.py`     | 재무제표 수집기 인터페이스                        |
| `data_pipeline/collectors/financial_statements/config.py`   | 수집 대상 universe 설정                           |
| `data_pipeline/collectors/financial_statements/yfinance.py` | yfinance 기반 재무제표 수집 및 정규화             |
| `data_pipeline/orchestrator.py`                             | 병렬 수집 실행 및 DB 저장 호출                    |
| `data_pipeline/database.py`                                 | `financial_statement_items` 테이블 생성 및 upsert |
| `data_pipeline/scheduler.py`                                | 매일 05:00 정기 수집 등록                         |

## 실행 흐름

1. `EarningsOrchestrator.sync_financial_statements()`가 호출된다.
2. 수집 대상 ticker 목록을 결정한다.
3. `ThreadPoolExecutor`로 ticker별 수집을 병렬 실행한다.
4. 각 ticker에 대해 `YFinanceFinancialStatementStrategy.collect(ticker)`가 실행된다.
5. yfinance에서 분기 손익계산서, 재무상태표, 현금흐름표를 조회한다.
6. yfinance DataFrame을 row 단위 record로 펼친다.
7. 수집 결과가 있으면 `database.save_financial_statement_items()`로 저장한다.
8. 저장 시 테이블이 없으면 `CREATE TABLE IF NOT EXISTS`로 먼저 생성한다.

## 수집 대상 Universe

기본 universe는 `m7`이다.

```python
M7_TICKERS = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA"]
```

지원하는 universe:

| universe       | 설명                                                       |
| -------------- | ---------------------------------------------------------- |
| `m7`           | Magnificent 7 고정 목록                                    |
| `stocks_table` | DB의 `stocks` 테이블 전체 ticker                           |
| `sp500`        | `stocks_table`과 동일하게 `stocks` 테이블 전체 ticker 사용 |

환경 변수로 기본 universe를 바꿀 수 있다.

```powershell
$env:FINANCIAL_STATEMENT_UNIVERSE = "stocks_table"
```

또는 실행 시 직접 인자로 넘길 수 있다.

```powershell
..\myenv\Scripts\python.exe -X utf8 -c "from orchestrator import EarningsOrchestrator; EarningsOrchestrator().sync_financial_statements('m7', 5)"
```

## 수집 데이터 형태

yfinance는 보통 다음 형태의 DataFrame을 반환한다.

| index         | 2025-03-31 | 2024-12-31 | ... |
| ------------- | ---------: | ---------: | --- |
| Total Revenue |     100000 |      90000 | ... |
| Net Income    |      20000 |      18000 | ... |

`YFinanceFinancialStatementStrategy._statement_to_records()`는 이를 다음 record 목록으로 변환한다.

```python
{
    "ticker": "AAPL",
    "statement_type": "income_statement",
    "fiscal_period_end": date(2025, 3, 31),
    "frequency": "quarterly",
    "line_item": "Total Revenue",
    "value": 100000.0,
    "source": "yfinance",
    "collected_at": datetime(...)
}
```

변환 규칙:

| 항목                                | 처리 방식           |
| ----------------------------------- | ------------------- |
| 빈 DataFrame                        | 저장하지 않음       |
| `NaN` 값                            | 저장하지 않음       |
| 숫자로 변환할 수 없는 값            | 저장하지 않음       |
| 날짜로 변환할 수 없는 period column | 저장하지 않음       |
| MultiIndex column                   | 마지막 level만 사용 |

## 저장 테이블

테이블명은 `financial_statement_items`이다.

```sql
CREATE TABLE IF NOT EXISTS financial_statement_items (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    statement_type VARCHAR(32) NOT NULL,
    fiscal_period_end DATE NOT NULL,
    frequency VARCHAR(16) NOT NULL,
    line_item VARCHAR(128) NOT NULL,
    value DECIMAL(28, 4) NOT NULL,
    source VARCHAR(32) NOT NULL,
    collected_at DATETIME NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_financial_statement_items (
        ticker,
        statement_type,
        fiscal_period_end,
        frequency,
        line_item
    ),
    INDEX idx_fsi_ticker_period (ticker, fiscal_period_end),
    INDEX idx_fsi_statement_type (statement_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

중복 기준은 다음 5개 컬럼이다.

```text
ticker, statement_type, fiscal_period_end, frequency, line_item
```

이미 같은 항목이 있으면 `value`, `source`, `collected_at`만 업데이트한다.

## 정기 실행

`data_pipeline/scheduler.py`에서 매일 05:00에 실행되도록 등록되어 있다.

```python
scheduler.add_job(
    orch.sync_financial_statements,
    "cron",
    hour=5,
    minute=0,
    args=["m7", 5],
)
```

현재 스케줄러 기준:

| 항목           | 값    |
| -------------- | ----- |
| 실행 주기      | 매일  |
| 실행 시간      | 05:00 |
| universe       | `m7`  |
| 병렬 worker 수 | 5     |

## 수동 실행

`data_pipeline` 디렉터리에서 실행한다.

```powershell
cd data_pipeline
..\myenv\Scripts\python.exe -X utf8 -c "from orchestrator import EarningsOrchestrator; EarningsOrchestrator().sync_financial_statements()"
```

M7만 명시적으로 수집:

```powershell
..\myenv\Scripts\python.exe -X utf8 -c "from orchestrator import EarningsOrchestrator; EarningsOrchestrator().sync_financial_statements('m7', 5)"
```

`stocks` 테이블 전체 ticker 수집:

```powershell
..\myenv\Scripts\python.exe -X utf8 -c "from orchestrator import EarningsOrchestrator; EarningsOrchestrator().sync_financial_statements('stocks_table', 5)"
```

## 의존성

`data_pipeline/requirements.txt` 기준 주요 의존성:

| 패키지          | 용도                    |
| --------------- | ----------------------- |
| `yfinance`      | 재무제표 데이터 조회    |
| `pandas`        | yfinance DataFrame 처리 |
| `SQLAlchemy`    | DB 연결 및 쿼리 실행    |
| `PyMySQL`       | MySQL 드라이버          |
| `python-dotenv` | `.env` 환경 변수 로드   |

## DB 연결 설정

`database.py`는 `DB_URL` 환경 변수를 우선 사용한다.

```python
DB_URL = os.getenv(
    "DB_URL",
    "mysql+pymysql://root:password@localhost:3306/graduate_project",
)
```

별도 `.env`가 없으면 기본적으로 `graduate_project` 데이터베이스에 저장된다.

예시 `.env`:

```env
DB_URL=mysql+pymysql://root:password@localhost:3306/graduate_project
FINANCIAL_STATEMENT_UNIVERSE=m7
```

## 테스트

재무제표 변환 로직 테스트는 `data_pipeline/tests/test_financial_statements.py`에 있다.

실행:

```powershell
cd data_pipeline
..\myenv\Scripts\python.exe -m unittest tests.test_financial_statements
```

테스트 범위:

| 테스트                                                         | 검증 내용                           |
| -------------------------------------------------------------- | ----------------------------------- |
| `test_statement_to_records_flattens_quarterly_dataframe`       | 분기 DataFrame을 저장 record로 변환 |
| `test_statement_to_records_skips_empty_and_non_numeric_values` | 빈 값과 비숫자 값 제외              |
| `test_m7_universe_defaults_to_expected_tickers`                | 기본 M7 ticker 목록                 |

## 운영 주의사항

1. yfinance는 외부 네트워크를 사용하므로 인터넷 연결이 필요하다.
2. 프록시 환경 변수가 잘못 잡혀 있으면 yfinance 요청이 실패할 수 있다.
3. `stocks_table` 또는 `sp500` universe를 쓰려면 `stocks` 테이블에 ticker가 먼저 저장되어 있어야 한다.
4. yfinance가 특정 ticker 또는 특정 재무제표를 비워서 반환할 수 있다. 이 경우 해당 항목은 저장되지 않는다.
5. 병렬 worker 수를 너무 크게 잡으면 yfinance 요청 실패 또는 제한이 늘어날 수 있다.
6. Windows 콘솔에서 이모지 로그가 깨질 수 있으므로 수동 실행 시 `-X utf8` 옵션을 권장한다.

## 문제 해결

### 수집 결과가 없는 경우

확인할 항목:

```powershell
..\myenv\Scripts\python.exe -X utf8 -c "from collectors.financial_statements import get_m7_tickers; print(get_m7_tickers())"
```

`stocks_table` universe를 사용하는 경우:

```sql
SELECT COUNT(*) FROM stocks;
SELECT ticker FROM stocks LIMIT 10;
```

### DB에 저장되지 않는 경우

DB 연결 대상 확인:

```powershell
..\myenv\Scripts\python.exe -X utf8 -c "import database; print(database.DB_URL); print(database.engine.url.database)"
```

테이블 생성 여부 확인:

```sql
SHOW TABLES LIKE 'financial_statement_items';
```

저장 건수 확인:

```sql
SELECT ticker, statement_type, COUNT(*) AS item_count
FROM financial_statement_items
GROUP BY ticker, statement_type
ORDER BY ticker, statement_type;
```

## 확장 방향

현재 구조는 `FinancialStatementCollector` 인터페이스와 `CollectorChain`을 사용하므로, 다른 데이터 공급자를 추가하기 쉽다.

예상 확장 예:

| 확장                          | 방법                                                              |
| ----------------------------- | ----------------------------------------------------------------- |
| FMP, Finnhub 등 추가 provider | `FinancialStatementCollector` 구현체 추가                         |
| yfinance 실패 시 fallback     | `CollectorChain([YFinanceStrategy(), FMPStrategy()])` 형태로 구성 |
| annual 재무제표 추가          | `frequency` 인자와 yfinance 호출 옵션 확장                        |
| 저장 전 품질 검증             | ticker, period, line item 기준 validation layer 추가              |
