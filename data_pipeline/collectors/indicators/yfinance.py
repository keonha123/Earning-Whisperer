import yfinance as yf
from .base import IndicatorCollector
from typing import List, Dict

class YFinanceIndicatorStrategy(IndicatorCollector):
    def collect(self, ticker_list: List[str]) -> List[Dict]:
        if not ticker_list: return []

        print(f"📊 [Indicators] {len(ticker_list)}개 종목의 1년치 일봉 분석 시작...")
        
        # 1년치(1y) 일봉(1d)을 벌크로 가져와 API 호출 횟수 최적화
        data = yf.download(ticker_list, period="1y", interval="1d", group_by='ticker', progress=False)
        
        results = []
        for ticker in ticker_list:
            try:
                # 결측치 제거 후 데이터 확보
                df = data[ticker].dropna()
                if df.empty: continue
                
                # [박제용 데이터 연산]
                high_52w = float(df['High'].max())
                avg_vol_20d = float(df['Volume'].tail(20).mean())
                
                results.append({
                    'ticker': ticker,
                    'high_52w': high_52w,
                    'avg_volume_20d': avg_vol_20d
                })
            except Exception as e:
                print(f"⚠️ {ticker} 지표 계산 실패: {e}")
                
        return results