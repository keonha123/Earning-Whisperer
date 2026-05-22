import asyncio
import random
from data_pipeline.database import get_all_stocks 
from data_pipeline.stt_worker.core.agent_test2 import EarningsAgent
import datetime

async def run_individual_test(semaphore, stock, log_file):
    async with semaphore:
        ticker = stock['ticker']
        url = stock.get('ir_url')
        
        if not url:
            return ticker, "No URL"
        
        await asyncio.sleep(random.uniform(1, 5))
        agent = EarningsAgent(ticker, url)
        
        try:
            # 개별 요원의 총 활동 시간을 40초로 제한
            success = await asyncio.wait_for(agent.monitor(), timeout=40)
            status = "SUCCESS" if success else "FAILED"
        except asyncio.TimeoutError:
            status = "TIMEOUT"
        except Exception as e:
            status = f"ERROR: {str(e)[:15]}"

        # [수정 포인트] 로그 라인에 URL 추가 (Status 뒤에 구분자 '|'를 넣어 가독성 확보)
        result_line = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {ticker}: {status.ljust(8)} | URL: {url}\n"
        
        # 콘솔 출력도 URL을 포함하면 더 편합니다.
        print(f"📊 {ticker}: {status.ljust(8)} | {url}")
        
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(result_line)
            
        return ticker, status

async def main():
    stocks = get_all_stocks() 
    log_filename = "earning_agent_report_fast.txt"
    
    # 동시성 설정 (사용자님의 환경에 맞춰 5~15 사이 조절)
    semaphore = asyncio.Semaphore(4)
    
    start_time = datetime.datetime.now()
    print(f"🚀 {len(stocks)}개 기업 고속 검사 시작 (동시성: 4)")
    print(f"📝 결과 파일: {log_filename}\n")

    tasks = [run_individual_test(semaphore, stock, log_filename) for stock in stocks]
    await asyncio.gather(*tasks)
    
    end_time = datetime.datetime.now()
    duration = end_time - start_time
    print(f"\n✅ 전체 검사 완료! 소요 시간: {duration}")

if __name__ == "__main__":
    asyncio.run(main())