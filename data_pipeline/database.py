# database.py
from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv
from typing import List, Dict

# 환경 변수 로드
load_dotenv()
DB_URL = os.getenv("DB_URL", "mysql+pymysql://root:password@localhost:3306/graduate_project")
engine = create_engine(DB_URL)

# --- 1. 종목 리스트 저장 (stocks 테이블) ---
def save_stocks(stock_list: List[Dict]):
    """S&P 500 등 종목 마스터 정보를 저장"""
    if not stock_list: return
    
    query = text("""
        INSERT INTO stocks (ticker, company_name, sector)
        VALUES (:ticker, :company_name, :sector)
        ON DUPLICATE KEY UPDATE 
            company_name = VALUES(company_name),
            sector = VALUES(sector)
    """)
    
    with engine.begin() as conn:
        for stock in stock_list:
            conn.execute(query, stock)
    print(f"💾 [Stocks] {len(stock_list)}개 종목 동기화 완료.")

# --- 2. 어닝 일정 저장 (calls 테이블) ---
def save_earnings_schedules(schedules: List[Dict]):
    """yfinance 등으로 수집한 어닝콜 날짜 정보를 저장"""
    if not schedules: return

    query = text("""
        INSERT INTO calls (ticker, earning_at, call_year, quarter, status)
        VALUES (:ticker, :earning_date, :call_year, :quarter, 'upcoming')
        ON DUPLICATE KEY UPDATE 
            earning_at = VALUES(earning_at),
            status = IF(status = 'completed', 'completed', 'upcoming')
    """)

    with engine.begin() as conn:
        for item in schedules:
            # 캘린더 날짜를 기반으로 연도/분기 계산 로직 추가 가능
            item['call_year'] = item['earning_date'].year
            item['quarter'] = f"Q{(item['earning_date'].month-1)//3 + 1}"
            conn.execute(query, item)
    print(f"💾 [Schedules] {len(schedules)}개 일정 업데이트 완료.")

# --- 3. 스트림 링크 업데이트 (calls 테이블) ---
def update_stream_link(ticker: str, video_url: str):
    """유튜브 등에서 찾은 실시간 링크를 기존 일정에 업데이트"""
    query = text("""
        UPDATE calls 
        SET video_url = :video_url, status = 'live'
        WHERE ticker = :ticker AND status = 'upcoming'
        ORDER BY earning_at ASC LIMIT 1
    """)
    
    with engine.begin() as conn:
        conn.execute(query, {"ticker": ticker, "video_url": video_url})

def get_all_tickers() -> List[str]:
    """stocks 테이블에서 모든 티커 리스트를 가져옴"""
    query = text("SELECT ticker FROM stocks")
    with engine.connect() as conn:
        result = conn.execute(query)
        # 리스트 형태로 변환하여 반환
        return [row[0] for row in result]
    
def save_prices(price_list: List[Dict]):
    if not price_list: return

    query = text("""
        INSERT IGNORE INTO prices 
        (ticker, price_at, open_price, high_price, low_price, close_price, volume)
        VALUES (:ticker, :price_at, :open_price, :high_price, :low_price, :close_price, :volume)
    """)

    try:
        with engine.begin() as conn:
            for price in price_list:
                conn.execute(query, price)
        print(f"💾 [DB] {price_list[0]['ticker']} 주가 데이터 {len(price_list)}건 저장 완료.")
    except Exception as e:
        print(f"❌ [DB] 주가 저장 에러: {e}")

def ensure_financial_statement_items_table():
    query = text("""
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
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    with engine.begin() as conn:
        conn.execute(query)


def save_financial_statement_items(statement_items: List[Dict]):
    if not statement_items:
        return

    ensure_financial_statement_items_table()

    query = text("""
        INSERT INTO financial_statement_items
            (
                ticker,
                statement_type,
                fiscal_period_end,
                frequency,
                line_item,
                value,
                source,
                collected_at
            )
        VALUES
            (
                :ticker,
                :statement_type,
                :fiscal_period_end,
                :frequency,
                :line_item,
                :value,
                :source,
                :collected_at
            )
        ON DUPLICATE KEY UPDATE
            value = VALUES(value),
            source = VALUES(source),
            collected_at = VALUES(collected_at)
    """)

    with engine.begin() as conn:
        for item in statement_items:
            conn.execute(query, item)

    tickers = sorted({item["ticker"] for item in statement_items})
    print(f"[DB] Saved {len(statement_items)} financial statement items for {len(tickers)} tickers.")


def update_static_indicators(indicator_list: List[Dict]):
    """stocks 테이블에 52주 고점 및 평균 거래량 정보를 박제(Update)"""
    if not indicator_list: return

    query = text("""
        UPDATE stocks 
        SET high_52w = :high_52w, 
            avg_volume_20d = :avg_volume_20d 
        WHERE ticker = :ticker
    """)

    with engine.begin() as conn:
        for item in indicator_list:
            conn.execute(query, item)
    print(f"💾 [DB] {len(indicator_list)}개 종목의 정적 지표 박제 완료.")
