import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

class YFinancePriceStrategy:
    def __init__(self):
        self.progress = False

    def _clean_df(self, df: pd.DataFrame, ticker: str) -> pd.DataFrame:
        """yfinance 특유의 Multi-index를 정리하고 표준 포맷으로 변환합니다."""
        if df.empty:
            return pd.DataFrame()

        # Multi-index 컬럼 압축 (Ticker 레벨 제거)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # 인덱스(시간)를 컬럼으로 빼내고 이름 통일
        df = df.reset_index()
        df.rename(columns={
            'Datetime': 'price_at', 
            'Date': 'price_at',
            'Open': 'open_price',
            'High': 'high_price',
            'Low': 'low_price',
            'Close': 'close_price',
            'Volume': 'volume'
        }, inplace=True)

        # 필요한 컬럼만 추출 및 티커 삽입
        cols = ['price_at', 'open_price', 'high_price', 'low_price', 'close_price', 'volume']
        df = df[cols].copy()
        df['ticker'] = ticker
        
        # 시간 포맷 표준화 (문자열)
        df['price_at'] = df['price_at'].dt.strftime('%Y-%m-%d %H:%M:%S')
        
        return df

    def collect_history(self, ticker: str, days: int = 7) -> list:
        """초기 DB 구축용: 최근 n일치 1분봉 데이터를 몽땅 가져옵니다."""
        print(f"📦 {ticker} 초기 데이터 수집 중 (최근 {days}일)...")
        # 1분봉은 최근 7일까지만 제공되는 경우가 많으므로 기본값을 7로 설정
        df = yf.download(ticker, period=f"{days}d", interval='1m', progress=self.progress)
        cleaned_df = self._clean_df(df, ticker)
        return cleaned_df.to_dict('records')

    def collect_latest(self, ticker: str) -> dict:
        """실시간 폴링용: 가장 최신의 1분봉 딱 하나만 가져옵니다."""
        # 1분봉 하나를 위해 1d period로 요청 (가장 안정적)
        df = yf.download(ticker, period='1d', interval='1m', progress=self.progress)
        cleaned_df = self._clean_df(df, ticker)
        
        if not cleaned_df.empty:
            # 가장 마지막 행(최신 데이터) 반환
            return cleaned_df.iloc[-1].to_dict()
        return None
    
    def collect(self, ticker: str, start: str = None, end: str = None) -> list:
        """
        오케스트라와 호환성을 맞추기 위한 '연결용' 함수입니다.
        기존 orchestrator가 이 이름을 호출하므로, 내부적으로 
        우리가 만든 새 로직을 연결해줍니다.
        """
        # 만약 start/end 정보가 넘어온다면 '과거 데이터 수집'으로 판단
        if start or end:
            # 적당히 일수를 계산하거나, 그냥 7일치(기본값)를 가져오도록 연결
            return self.collect_history(ticker, days=7)
        
        # 정보가 없다면 실시간 1건 수집으로 처리
        latest = self.collect_latest(ticker)
        return [latest] if latest else []