"""Stock universe, prices, indicators and financial statements."""

from sqlalchemy import text
from typing import Dict, List
from . import connection, schema


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
    
    with connection.engine.begin() as conn:
        for stock in stock_list:
            conn.execute(query, stock)
    print(f"💾 [Stocks] {len(stock_list)}개 종목 동기화 완료.")


def get_all_tickers() -> List[str]:
    """stocks 테이블에서 모든 티커 리스트를 가져옴"""
    query = text("SELECT ticker FROM stocks")
    with connection.engine.connect() as conn:
        result = conn.execute(query)
        # 리스트 형태로 변환하여 반환
        return [row[0] for row in result]


def get_all_stocks() -> List[Dict]:
    """stocks 테이블에서 discovery에 필요한 최소 종목 정보를 가져옴"""
    query = text("SELECT ticker, company_name, ir_url FROM stocks")
    with connection.engine.connect() as conn:
        result = conn.execute(query)
        return [dict(row._mapping) for row in result]


def update_stock_ir_url(ticker: str, ir_url: str):
    """발견한 IR 페이지 URL을 stocks 테이블에 저장"""
    query = text("""
        UPDATE stocks
        SET ir_url = :ir_url
        WHERE ticker = :ticker
    """)

    with connection.engine.begin() as conn:
        conn.execute(query, {"ticker": ticker, "ir_url": ir_url})


def save_prices(price_list: List[Dict]):
    if not price_list: return

    query = text("""
        INSERT IGNORE INTO prices 
        (ticker, price_at, open_price, high_price, low_price, close_price, volume)
        VALUES (:ticker, :price_at, :open_price, :high_price, :low_price, :close_price, :volume)
    """)

    try:
        with connection.engine.begin() as conn:
            for price in price_list:
                conn.execute(query, price)
        print(f"💾 [DB] {price_list[0]['ticker']} 주가 데이터 {len(price_list)}건 저장 완료.")
    except Exception as e:
        print(f"❌ [DB] 주가 저장 에러: {e}")


def save_financial_statement_items(statement_items: List[Dict]):
    if not statement_items:
        return

    schema.ensure_financial_statement_items_table()

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

    with connection.engine.begin() as conn:
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

    with connection.engine.begin() as conn:
        for item in indicator_list:
            conn.execute(query, item)
    print(f"💾 [DB] {len(indicator_list)}개 종목의 정적 지표 박제 완료.")
