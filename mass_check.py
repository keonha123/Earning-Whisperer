import asyncio
from data_pipeline.database import get_all_stocks  # 수정된 database.py 필요
from agent import EarningsAgent
import datetime

async def run_individual_test(semaphore, stock, log_file):
    async with semaphore:
        ticker = stock['ticker']
        url = stock.get('ir_url')
        
        if not url:
            return ticker, "No URL"

        print(f"📡 [{ticker}] 검사 시작... ({url[:40]}...)")
        agent = EarningsAgent(ticker, url)
        
        # [중요] 대량 검사 시에는 headless=True로 설정하는 것이 시스템 자원에 좋습니다.
        # 필요하다면 agent.py의 launch 부분에 변수를 넘기도록 수정하세요.
        try:
            # 타임아웃을 40초 정도로 짧게 잡아서 빠르게 회전시킵니다.
            success = await asyncio.wait_for(agent.monitor(), timeout=45)
            status = "SUCCESS" if success else "FAILED"
        except asyncio.TimeoutError:
            status = "TIMEOUT"
        except Exception as e:
            status = f"ERROR: {str(e)[:30]}"

        result_line = f"[{datetime.datetime.now()}] {ticker}: {status}\n"
        print(f"📊 결과 보고 -> {ticker}: {status}")
        
        with open(log_file, "a") as f:
            f.write(result_line)
            
        return ticker, status

async def main():
    # 1. DB에서 URL 포함된 전체 리스트 확보
    stocks = get_all_stocks() 

    print(f"DEBUG: DB에서 가져온 종목 수: {len(stocks)}")
    if stocks:
        print(f"DEBUG: 첫 번째 종목 샘플: {stocks[0]}")

    log_filename = "earning_agent_report.txt"
    
    # 2. 세마포어 설정 (동시 실행 브라우저 수: 씽크패드 성능 고려 3~5개 추천)
    semaphore = asyncio.Semaphore(3) 
    
    print(f"🚀 총 {len(stocks)}개 기업에 대한 요원 투입을 시작합니다.")
    print(f"📝 결과는 {log_filename}에 실시간 저장됩니다.\n")

    tasks = [run_individual_test(semaphore, stock, log_filename) for stock in stocks]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())