# test_youtube.py
import os
from dotenv import load_dotenv
from data_pipeline.collectors.streams.youtube import YouTubeLiveStrategy

load_dotenv()

def test_search():
    # 1. 전략 인스턴스 생성
    strategy = YouTubeLiveStrategy()
    
    # 2. 테스트용 티커와 기업명 설정 
    # (현재 라이브가 있을 법한 키워드로 테스트해보세요. 예: NVDA, TSLA)
    test_ticker = "NVDA"
    test_company = "NVIDIA"
    
    print(f"🚀 {test_ticker}에 대한 유튜브 라이브 검색 테스트 시작...")
    
    # 3. 수집 실행
    url = strategy.collect(test_ticker, test_company)
    
    if url:
        print(f"✅ 테스트 성공! 찾은 URL: {url}")
    else:
        print("❌ 라이브 주소를 찾지 못했습니다. (검색 쿼리나 API 키 확인 필요)")

if __name__ == "__main__":
    test_search()