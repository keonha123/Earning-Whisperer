# collectors/stocks/wikipedia.py 수정본
import pandas as pd
import requests
import io # 이 줄이 추가되어야 최신 판다스에서 에러가 안 납니다.
from .base import StockListCollector

class WikipediaStrategy(StockListCollector):
    def collect(self) -> list[dict]:
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        headers = {'User-Agent': 'Mozilla/5.0'} # 위키피디아 거부 방지
        
        try:
            response = requests.get(url, headers=headers)
            # [핵심] match 옵션을 줘서 'Symbol' 컬럼이 있는 표만 찾습니다.
            # io.StringIO를 써서 문자열을 파일처럼 읽게 해줍니다.
            tables = pd.read_html(io.StringIO(response.text), match='Symbol')
            
            if not tables:
                return []

            df = tables[0]
            # 위키피디아 컬럼명에 맞춰서 정확히 추출
            df = df[['Symbol', 'Security', 'GICS Sector']]
            df.columns = ['ticker', 'company_name', 'sector']
            
            # 티커 특수문자 정제 (BRK.B -> BRK-B)
            df['ticker'] = df['ticker'].str.replace('.', '-', regex=False)
            
            return df.to_dict(orient='records')
            
        except Exception as e:
            # 여기서 에러 내용을 출력해보면 왜 else로 가는지 알 수 있습니다!
            print(f"❌ 위키피디아 수집기 내부 에러: {e}")
            return []