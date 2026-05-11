import asyncio
from playwright.async_api import async_playwright

class EarningsAgent:
    def __init__(self, ticker, ir_url):
        self.ticker = ticker
        self.ir_url = ir_url

    async def monitor(self):
        async with async_playwright() as p:
            # 1. 브라우저 실행 및 환경 설정
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(viewport={'width': 1280, 'height': 1000})
            page = await context.new_page()

            print(f"🚀 [{self.ticker}] 작전 개시: {self.ir_url}")

            try:
                # 페이지 접속 (충분한 로딩 시간 부여)
                await page.goto(self.ir_url, wait_until="load", timeout=60000)
                
                # [단계 1] 방해물 제거 (배너/팝업)
                print("🧹 방해 요소(배너) 제거 시도...")
                try:
                    # 'No. Keep me on the current site' 버튼이 있으면 클릭해서 배너 치우기
                    banner_btn = page.get_by_role("button", name="No. Keep me on the current site")
                    if await banner_btn.is_visible(timeout=5000):
                        await banner_btn.click()
                        print("✅ 지역 선택 배너를 닫았습니다.")
                except:
                    print("ℹ️ 닫을 배너가 없거나 이미 사라졌습니다.")

                # [단계 2] 모든 프레임을 관통하는 무한 수색 루프
                print(f"🕵️ [{self.ticker}] 모든 구역(Frame) 정밀 수색 중...")
                
                found_el = None
                for attempt in range(10): # 10번 재시도 (약 30~40초)
                    # 메인 페이지를 포함한 모든 프레임 리스트업
                    all_frames = page.frames
                    
                    for frame in all_frames:
                        # 텍스트로 직접 찾기 (나스닥 위젯 특징 반영)
                        target = frame.get_by_text("Click here for webcast", exact=False)
                        
                        # 텍스트가 존재하고, 실제로 상호작용 가능한지 확인
                        if await target.count() > 0:
                            if await target.first.is_visible():
                                found_el = target.first
                                print(f"🎯 발견! [구역: {frame.name or 'Main'}]")
                                break
                    
                    if found_el: break
                    print(f"🔄 {attempt+1}회차 수색 실패... 다시 찾는 중")
                    await asyncio.sleep(3)

                if not found_el:
                    print("❌ 모든 구역을 뒤졌으나 목표를 찾지 못했습니다. 수동 확인이 필요합니다.")
                    # 현재 페이지에 있는 모든 텍스트를 로그로 남겨서 사각지대 파악
                    # content = await page.content()
                    # with open("debug_page.html", "w") as f: f.write(content)
                    return

                # [단계 3] 시각화 및 진입
                await found_el.evaluate("el => el.style.border = '10px solid red'")
                await found_el.scroll_into_view_if_needed()
                print("🖱️ 목표물 클릭 및 진입!")
                
                # 일반 클릭이 안될 경우를 대비한 강제 클릭
                await found_el.click(force=True)

                # 페이지 이동 대기
                await page.wait_for_load_state("networkidle")
                print(f"✨ 진입 성공: {page.url}")

                # 1시간 대기 (눈으로 확인)
                await asyncio.sleep(3600)

            except Exception as e:
                print(f"❌ 오류 발생: {e}")
            finally:
                await browser.close()

if __name__ == "__main__":
    XYL_URL = "https://www.xylem.com/en-us/investors/events/"
    agent = EarningsAgent("XYL", XYL_URL)
    asyncio.run(agent.monitor())