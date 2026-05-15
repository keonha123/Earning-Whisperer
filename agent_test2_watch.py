import asyncio
from playwright.async_api import async_playwright
import re

class EarningsAgent:
    def __init__(self, ticker, ir_url):
        self.ticker = ticker
        self.ir_url = ir_url

    async def monitor(self):
        async with async_playwright() as p:
            # 시각적 확인을 위해 창을 띄웁니다.
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(viewport={'width': 1280, 'height': 1000})
            page = await context.new_page()

            try:
                print(f"🚀 [{self.ticker}] 작전 시작: {self.ir_url}")
                await page.goto(self.ir_url, wait_until="load", timeout=30000)
                await asyncio.sleep(2)

                found_el = None
                
                # [단계 1] 모든 프레임 탐색
                for frame in page.frames:
                    # 'Webcast' 문구가 들어간 모든 링크/버튼 추출
                    candidates = frame.locator("a, button").filter(
                        has_text=re.compile(r"Webcast|Listen|Join|Audio", re.IGNORECASE)
                    )
                    
                    count = await candidates.count()
                    for i in range(count):
                        candidate = candidates.nth(i)
                        
                        # [단계 2] 부모 구역 찾기 (어도비 같은 일반 구조 대응을 위해 로직 수정)
                        # 특정 클래스가 없더라도, 해당 링크를 감싸고 있는 가장 가까운 구획(div나 section)을 찾습니다.
                        parent_area = candidate.locator("xpath=./ancestor::div[contains(@class, 'block')] | ./ancestor::div[contains(@class, 'section')] | ./ancestor::article | ./ancestor::div[contains(@style, 'display')]")
                        
                        # 만약 위 조건에 맞는 부모가 없다면, 그냥 바로 위 부모 div를 가져옵니다. (폴백 로직)
                        if await parent_area.count() == 0:
                            parent_area = candidate.locator("xpath=./parent::*")

                        context_text = await parent_area.first.inner_text()
                        
                        # [날짜 체크 주석 처리] - 사용자 요청에 따라 과거 링크라도 일단 타게 함
                        # if "2026" in context_text: 
                        #    print(f"📅 날짜 확인됨: {context_text[:30]}...")

                        if await candidate.is_visible():
                            found_el = candidate
                            break
                    if found_el: break

                if not found_el:
                    print(f"❌ [{self.ticker}] 웹캐스트 링크를 찾을 수 없습니다.")
                    return False

                # --- [시각적 확인 로직] ---
                
                # 1. 타겟으로 화면 이동
                await found_el.scroll_into_view_if_needed()
                
                # 2. 빨간색 테두리와 노란색 배경으로 강조 (강력한 시각 효과)
                print(f"🎯 [{self.ticker}] 타겟 발견! 화면에 표시합니다.")
                await found_el.evaluate("""el => {
                    el.style.outline = '10px solid red'; 
                    el.style.backgroundColor = 'yellow';
                    el.style.color = 'black';
                    el.style.zIndex = '9999';
                    el.style.position = 'relative';
                }""")
                
                # 3. 눈으로 확인하도록 4초간 정지
                await asyncio.sleep(4)
                
                # 4. 클릭 실행
                print(f"🖱️ [{self.ticker}] 링크 클릭 후 이동합니다.")
                await found_el.click(force=True)
                
                # 5. 이동 후 페이지가 뜰 때까지 잠시 대기 (결과 확인용)
                await page.wait_for_load_state("networkidle", timeout=10000)
                await asyncio.sleep(5) 
                
                return True

            except Exception as e:
                print(f"⚠️ 에러: {e}")
                return False
            finally:
                await browser.close()

if __name__ == "__main__":
    # 어도비 URL로 테스트
    ADBE_URL = "https://investor.zoetis.com/events-and-presentations/default.aspx"
    agent = EarningsAgent("ZTS", ADBE_URL)
    asyncio.run(agent.monitor())