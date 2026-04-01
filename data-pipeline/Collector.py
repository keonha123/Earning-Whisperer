#pip install apscheduler
from apscheduler.schedulers.background import BackgroundScheduler
import time
from datetime import datetime
# 1. 실제 수집 로직 (야후에서 가져온다고 가정)
def collect_sp500_rank():
    print(f"[{datetime.now()}] S&P 500 리스트 및 시총 순위 갱신 시작...")
    # 여기에 아까 만든 SlickCharts나 Yahoo 수집 코드가 들어갑니다.
    # 성공 시 DB에 저장하는 로직 포함
    print("성공적으로 리스트를 갱신했습니다.")

def collect_upcoming_earnings():
    print(f"[{datetime.now()}] 이번 주 어닝콜 일정 체크 중...")
    # 이번 주 실적 발표 기업 티커들을 가져와 DB에 업데이트
    print("어닝콜 일정을 최신화했습니다.")

def collect_realtime_prices():
    print(f"[{datetime.now()}] 주요 종목 실시간 주가 수집...")
    # 상위 종목 위주로 주가 업데이트
    print("주가 최신화 완료.")

# 2. 스케줄러 설정
scheduler = BackgroundScheduler()

# 3. 주기 설정 (3번 전략 반영)
# 매주 월요일 새벽 3시에 전체 리스트 갱신
scheduler.add_job(collect_sp500_rank, 'cron', day_of_week='mon', hour=3, minute=0)

# 매일 새벽 4시에 어닝 일정 갱신
scheduler.add_job(collect_upcoming_earnings, 'cron', hour=4, minute=0)

# 평일(월-금) 오전 9시부터 오후 4시까지 15분마다 주가 갱신
scheduler.add_job(collect_realtime_prices, 'cron', day_of_week='mon-fri', hour='9-16', minute='*/15')

# 4. 스케줄러 시작
scheduler.start()

print("데이터 수집 서버가 가동되었습니다. 컨트롤+C를 누르면 종료됩니다.")

try:
    # 서버가 종료되지 않도록 무한 루프 유지
    while True:
        time.sleep(1)
except (KeyboardInterrupt, SystemExit):
    scheduler.shutdown()
    print("서버를 안전하게 종료합니다.")