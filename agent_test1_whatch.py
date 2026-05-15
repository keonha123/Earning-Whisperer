import asyncio
from playwright.async_api import async_playwright
import re

class EarningsAgent:
    def __init__(self, ticker, ir_url):
        self.ticker = ticker
        self.ir_url = ir_url
        self.target_date_str = "May 07, 2026" 

    async def monitor(self):
        async with async_playwright() as p:
            # 시각적 확인을 위해 headless=False와 느린 동작(slow_mo)을 추가할 수 있습니다.
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(viewport={'width': 1280, 'height': 1000})
            page = await context.new_page()

            try:
                print(f"🕵️ [{self.ticker}] 페이지 접속 중...")
                await page.goto(self.ir_url, wait_until="load", timeout=30000)
                await asyncio.sleep(2)

                found_el = None
                
                # [수색 단계] 기존 로직 유지
                for frame in page.frames:
                    candidates = frame.locator("a, button, [role='button']").filter(
                        has_text=re.compile(r"Webcast|Listen|Join|Audio", re.IGNORECASE)
                    )
                    
                    count = await candidates.count()
                    for i in range(count):
                        candidate = candidates.nth(i)
                        parent_area = candidate.locator("xpath=./ancestor::div[contains(@class, 'item')] | ./ancestor::article")
                        
                        if await parent_area.count() > 0:
                            if await candidate.is_visible():
                                found_el = candidate
                                break
                    if found_el: break

                if not found_el:
                    print(f"❌ [{self.ticker}] 타겟 요소를 찾지 못했습니다.")
                    return False

                # --- [시각적 확인 코드 추가 구간] ---
                
                # 1. 요소를 화면 중앙으로 스크롤
                await found_el.scroll_into_view_if_needed()
                
                # 2. 빨간색 테두리로 강조 (Highlight)
                print(f"🎯 [{self.ticker}] 타겟 발견! 빨간색 테두리로 표시합니다.")
                await found_el.evaluate("el => { el.style.border = '5px solid red'; el.style.backgroundColor = 'yellow'; }")
                
                # 3. 눈으로 확인할 시간을 줍니다 (3초 대기)
                await asyncio.sleep(3)
                
                # 4. 클릭 액션 (강제 클릭)
                print(f"🖱️ [{self.ticker}] 클릭 실행!")
                await found_el.click(force=True)
                
                # --- [시각적 확인 코드 종료] ---

                try:
                    # 클릭 후 페이지 이동 및 로딩 확인을 위해 5초간 더 열어둡니다.
                    print(f"⏳ [{self.ticker}] 이동 중... 결과 확인을 위해 잠시 대기합니다.")
                    await page.wait_for_load_state("networkidle", timeout=15000)
                    await asyncio.sleep(5) 
                    return True 
                except:
                    return True

            except Exception as e:
                print(f"⚠️ [{self.ticker}] 에러 발생: {e}")
                return False
            finally:
                # 확인이 끝나면 브라우저를 닫습니다.
                await browser.close()

if __name__ == "__main__":
    # 테스트용
    XYL_URL = "https://www.adobe.com/investor-relations.html?promoid=2XBSC4VN&mv=other"
    agent = EarningsAgent("ADBE", XYL_URL)
    asyncio.run(agent.monitor())