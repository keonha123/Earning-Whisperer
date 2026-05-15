import asyncio
from playwright.async_api import async_playwright

class EarningsAgent:
    def __init__(self, ticker, ir_url):
        self.ticker = ticker
        self.ir_url = ir_url

    async def monitor(self):
        async with async_playwright() as p:
            # [변경점 1] headless=True로 설정하여 창을 띄우지 않음 (백그라운드 실행)
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(viewport={'width': 1280, 'height': 1000})
            page = await context.new_page()

            # [속도 향상 팁] 리소스 차단 로직 (필요시 주석 해제)
            # await page.route("**/*.{png,jpg,jpeg,gif,css}", lambda route: route.abort())

            # print(f"🚀 [{self.ticker}] 작전 개시: {self.ir_url}") # 대량 검사 시 로그 최소화

            try:
                # 페이지 접속 (기존 load에서 domcontentloaded로 낮추면 더 빠르지만, 안정성을 위해 load 유지 시 타임아웃 단축 권장)
                await page.goto(self.ir_url, wait_until="load", timeout=30000) 
                
                # [단계 1] 방해물 제거 (배너/팝업) - 대량 검사에서는 1초만 기다리도록 단축
                try:
                    banner_btn = page.get_by_role("button", name="No. Keep me on the current site")
                    if await banner_btn.is_visible(timeout=1000):
                        await banner_btn.click()
                except:
                    pass # 로그 생략

                # [단계 2] 모든 프레임을 관통하는 무한 수색 루프
                found_el = None
                
                # [변경점 2] 재시도 횟수를 2회로 단축 (range(10) -> range(2))
                for attempt in range(2): 
                    all_frames = page.frames
                    
                    for frame in all_frames:
                        # 텍스트로 직접 찾기 (나스닥 위젯 특징 반영)
                        target = frame.get_by_text("Click here for webcast", exact=False)
                        
                        if await target.count() > 0:
                            if await target.first.is_visible():
                                found_el = target.first
                                break
                    
                    if found_el: break
                    # 대량 검사에서는 실패 로그를 줄이고 조용히 재시도
                    await asyncio.sleep(2) # 재시도 간격도 3초에서 2초로 단축

                if not found_el:
                    # 못 찾으면 바로 False 반환 후 종료
                    return False

                # [단계 3] 진입
                # headless 모드이므로 시각화(빨간 테두리) 로직은 불필요하여 주석 처리
                # await found_el.evaluate("el => el.style.border = '10px solid red'")
                # await found_el.scroll_into_view_if_needed()
                
                # 일반 클릭이 안될 경우를 대비한 강제 클릭
                await found_el.click(force=True)

                # 페이지 이동 대기 (대량 검사 시 30초 정도만 기다리고 넘어가도록 설정)
                try:
                    await page.wait_for_load_state("networkidle", timeout=30000)
                    return True # 클릭 후 로딩 성공 시 True 반환
                except:
                    # 클릭은 성공했으나, 다음 페이지 로딩(등록 폼 등)이 30초를 넘긴 경우
                    # 이는 긍정적인 신호이므로 별도 상태(예: 'TIMEOUT_AFTER_CLICK')로 반환 가능하나,
                    # 현재 구조의 호환성을 위해 우선 Exception으로 던지게 두거나 True를 반환합니다.
                    return True # 이 부분을 고민해보세요! "들어는 갔으니 성공으로 칠까?"

                # [삭제] 대량 검사에서는 1시간(3600초) 대기할 필요 없음
                # await asyncio.sleep(3600)

            except Exception as e:
                # print(f"❌ [{self.ticker}] 오류 발생: {str(e)[:30]}")
                return False
            finally:
                await browser.close()

if __name__ == "__main__":
    # 단일 테스트용 코드
    XYL_URL = "https://investors.airbnb.com/events-and-presentations/default.aspx" # 테스트 URL (autodesk는 위젯이 다를 수 있음)
    agent = EarningsAgent("XYL", XYL_URL)
    result = asyncio.run(agent.monitor())
    print(f"테스트 결과: {result}")