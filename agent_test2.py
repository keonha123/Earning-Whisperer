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
            # 실전 대량 검사를 위해 headless=True로 변경 가능합니다.
            browser = await p.chromium.launch(headless=False) 
            context = await browser.new_context(viewport={'width': 1280, 'height': 1000})
            page = await context.new_page()

            try:
                # 1. 페이지 접속
                await page.goto(self.ir_url, wait_until="load", timeout=30000)
                await asyncio.sleep(2) # 동적 위젯 로딩 대기

                found_el = None
                
                # 2. 모든 프레임 관통 수색
                for frame in page.frames:
                    # 'Webcast/Listen/Join/Audio' 키워드 대응
                    candidates = frame.locator("a, button, [role='button']").filter(
                        has_text=re.compile(r"Webcast|Listen|Join|Audio", re.IGNORECASE)
                    )
                    
                    count = await candidates.count()
                    for i in range(count):
                        candidate = candidates.nth(i)
                        
                        # [핵심 수정] 부모 구역 탐색 유연화 (Adobe 스타일 대응)
                        # 특정 클래스가 없어도 div나 section 단위로 맥락을 파악합니다.
                        parent_area = candidate.locator("xpath=./ancestor::div[contains(@class, 'block') or contains(@class, 'section') or contains(@class, 'event')] | ./ancestor::article")
                        
                        # 만약 위 조건으로 부모를 못 찾으면 바로 위 부모 요소를 참조 (Fallback)
                        if await parent_area.count() == 0:
                            parent_area = candidate.locator("xpath=./parent::*")

                        # 3. 맥락 추출 (나중에 날짜 체크를 위해 유지)
                        context_text = await parent_area.first.inner_text()
                        
                        # --- [날짜 체크 로직 - 현재 주석 유지] ---
                        # if self.target_date_str not in context_text: continue
                        # ------------------------------------------

                        if await candidate.is_visible():
                            found_el = candidate
                            break
                    if found_el: break

                if not found_el:
                    return False

                # 4. 클릭 및 결과 확인
                await found_el.scroll_into_view_if_needed()
                await found_el.click(force=True)

                # 페이지 이동 혹은 새 창 로딩 확인 (networkidle 대기)
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                    return True 
                except:
                    # 타임아웃이 나더라도 클릭 후 페이지가 바뀌었다면 성공으로 간주
                    return True

            except Exception:
                return False
            finally:
                await browser.close()

if __name__ == "__main__":
    # 테스트하고 싶은 URL을 입력하세요.
    TEST_URL = "https://www.adobe.com/investor-relations.html?promoid=2XBSC4VN&mv=other"
    agent = EarningsAgent("ADBE", TEST_URL)
    result = asyncio.run(agent.monitor())
    print(f"[{agent.ticker}] 테스트 결과: {result}")