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
                        
                        # 💡 [추가된 핵심 로직] 내비게이션 바, 사이드바, 헤더/푸터 영역 내부의 엘리먼트인지 검사
                        is_menu_element = await candidate.evaluate("""el => {
                            let parent = el.parentElement;
                            while (parent) {
                                const tagName = parent.tagName.toLowerCase();
                                const className = parent.className ? String(parent.className).toLowerCase() : '';
                                const idName = parent.id ? String(parent.id).toLowerCase() : '';
                                
                                // 내비게이션, 헤더, 푸터, 사이드바 관련 태그나 클래스명/ID가 있으면 메뉴로 판단
                                if (
                                    tagName === 'nav' || 
                                    tagName === 'header' || 
                                    tagName === 'footer' ||
                                    className.includes('nav') || 
                                    className.includes('menu') || 
                                    className.includes('sidebar') ||
                                    idName.includes('nav') ||
                                    idName.includes('sidebar')
                                ) {
                                    return true;
                                }
                                parent = parent.parentElement;
                            }
                            return false;
                        }""")

                        if is_menu_element:
                            # 사이드바나 상단 메뉴에 있는 링크는 우리가 찾는 본문 링크가 아니므로 패스합니다.
                            continue

                        if not await candidate.is_visible():
                            continue

                        # [단계 2] 부모 구역 찾기 (어도비 같은 일반 구조 대응을 위해 로직 유지)
                        parent_area = candidate.locator("xpath=./ancestor::div[contains(@class, 'block')] | ./ancestor::div[contains(@class, 'section')] | ./ancestor::article | ./ancestor::div[contains(@style, 'display')]")
                        
                        if await parent_area.count() == 0:
                            parent_area = candidate.locator("xpath=./parent::*")

                        context_text = await parent_area.first.inner_text()
                        
                        # 모든 필터를 통과한 진짜 본문 링크 확보
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
    # 신타스 URL로 테스트
    CINTAS_URL = "https://www.cintas.com/investors/earnings-webcast/event-details"
    agent = EarningsAgent("CTAS", CINTAS_URL)
    asyncio.run(agent.monitor())