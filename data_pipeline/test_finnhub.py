import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
# 1. .env 로드 및 키 확인
load_dotenv()
api_key = 'd7voimpr01qj3ct7qub0d7voimpr01qj3ct7qubg'
print("--- [환경 변수 체크] ---")
if not api_key:
    print("❌ 에러: .env 파일에서 FINNHUB_API_KEY를 찾을 수 없습니다.")
    exit()
else:
    print(f"✅ 키 로드 성공: {api_key[:5]}******")

# 2. 테스트 설정 (향후 30일간의 AAPL 일정 조회)
ticker = "Q"  # 테스트용 티커
start_date = datetime.now().strftime('%Y-%m-%d')
end_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
url = f"https://finnhub.io/api/v1/calendar/earnings?from={start_date}&to={end_date}&symbol={ticker}&token={api_key}"

print(f"\n--- [API 요청 테스트: {ticker}] ---")
try:
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        earnings = data.get("earningsCalendar", [])
        
        if not earnings:
            print(f"ℹ️ 향후 30일 내에 {ticker}의 어닝 일정이 없습니다.")
        else:
            for item in earnings:
                print(f"📌 종목: {item.get('symbol')}")
                print(f"📅 날짜: {item.get('date')}")
                print(f"🕒 시간(raw): {item.get('hour')}") # 여기가 우리가 원하던 'amc', 'bmo' 혹은 'HH:mm'
                print(f"📝 전체 데이터: {item}")
    else:
        print(f"❌ 요청 실패: 상태 코드 {response.status_code}")
        print(response.text)

except Exception as e:
    print(f"❌ 오류 발생: {e}")