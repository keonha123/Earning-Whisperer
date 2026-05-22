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
                print(f"🚀 [{self.ticker}] 작전 시작: {self.ir_url}")
                await page.goto(self.ir_url, wait_until="load", timeout=30000)
                await asyncio.sleep(2) # 동적 위젯 로딩 대기

                found_el = None
                
                # 2. 모든 프레임 관통 수색
                for frame in page.frames:
                    # 'Webcast/Listen/Join/Audio' 키워드 및 다양한 역할(role) 대응
                    candidates = frame.locator("a, button, [role='button']").filter(
                        has_text=re.compile(r"Webcast|Listen|Join|Audio", re.IGNORECASE)
                    )
                    
                    count = await candidates.count()
                    for i in range(count):
                        candidate = candidates.nth(i)
                        
                        # 💡 [필터 로직] 상단 헤더, 내비게이션 바, 사이드바, 푸터 내부 엘리먼트인지 검사
                        is_menu_element = await candidate.evaluate("""el => {
                            let parent = el.parentElement;
                            while (parent) {
                                const tagName = parent.tagName.toLowerCase();
                                const className = parent.className ? String(parent.className).toLowerCase() : '';
                                const idName = parent.id ? String(parent.id).toLowerCase() : '';
                                
                                if (
                                    ['nav', 'header', 'footer'].includes(tagName) || 
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

                        # 메뉴 영역에 포함된 링크라면 본문이 아니므로 과감히 패스
                        if is_menu_element:
                            continue

                        if not await candidate.is_visible():
                            continue

                        # [부모 구역 탐색 유연화 - 원래 코드 구조 유지]
                        parent_area = candidate.locator("xpath=./ancestor::div[contains(@class, 'block') or contains(@class, 'section') or contains(@class, 'event')] | ./ancestor::article")
                        
                        # 만약 위 조건으로 부모를 못 찾으면 바로 위 부모 요소를 참조 (Fallback)
                        if await parent_area.count() == 0:
                            parent_area = candidate.locator("xpath=./parent::*")

                        # 3. 맥락 추출 (나중에 날짜 체크를 위해 유지)
                        context_text = await parent_area.first.inner_text()
                        
                        # --- [날짜 체크 로직 - 현재 주석 유지] ---
                        # if self.target_date_str not in context_text: continue
                        # ------------------------------------------

                        found_el = candidate
                        break
                    if found_el: break

                if not found_el:
                    print(f"❌ [{self.ticker}] 적절한 웹캐스트 링크를 찾지 못했습니다.")
                    return False

                # 4. 시각적 하이라이트 및 클릭 (디버깅 용이성 유지)
                await found_el.scroll_into_view_if_needed()
                
                print(f"🎯 [{self.ticker}] 타겟 본문 링크 발견! 화면에 표시합니다.")
                await found_el.evaluate("""el => {
                    el.style.outline = '10px solid red'; 
                    el.style.backgroundColor = 'yellow';
                    el.style.color = 'black';
                    el.style.zIndex = '9999';
                    el.style.position = 'relative';
                }""")
                await asyncio.sleep(3) # 눈으로 확인하기 위한 잠깐의 대기

                print(f"鼠标 [{self.ticker}] 링크 클릭 시도")
                await found_el.click(force=True)

                # 페이지 이동 혹은 새 창 로딩 확인 (networkidle 대기)
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                    print(f"✅ [{self.ticker}] 성공적으로 이동 및 로드 완료.")
                    await asyncio.sleep(3) # 최종 결과 확인용
                    return True 
                except:
                    # 타임아웃이 나더라도 클릭 후 페이지가 바뀌었다면 성공으로 간주
                    print(f"⚠️ [{self.ticker}] 네트워크 안정화 타임아웃되었으나 클릭은 성공한 것으로 간주합니다.")
                    return True

            except Exception as e:
                print(f"🚨 에러 발생: {e}")
                return False
            finally:
                await browser.close()

if __name__ == "__main__":
    # 테스트 타겟 변경 가능 (예: Cintas, Adobe 등)
    TEST_URL = "https://www.cintas.com/investors/earnings-webcast/event-details"
    agent = EarningsAgent("CTAS", TEST_URL)
    result = asyncio.run(agent.monitor())
    print(f"[{agent.ticker}] 최종 테스트 결과: {result}")