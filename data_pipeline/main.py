import asyncio
import scheduler 

async def main():
    print("🚀 [Earning Whisperer] 시스템 엔진 가동...")
    print("📂 실행 환경: data_pipeline 패키지 모드")
    
    try:
        # 중앙 스케줄러 가동
        await scheduler.start_scheduling()
    except (KeyboardInterrupt, SystemExit):
        print("\n👋 서버가 안전하게 종료되었습니다. 관제를 종료합니다.")

if __name__ == "__main__":
    # 비동기 실행 진입점
    asyncio.run(main())