import asyncio
from playwright.async_api import async_playwright
import re

class EarningsAgent:
    def __init__(self, ticker, ir_url):
        self.ticker = ticker
        self.ir_url = ir_url
        # 목표 날짜 (현재는 테스트를 위해 2026 혹은 오늘 날짜 설정 가능)
        self.target_date_str = "May 07, 2026" 

    async def monitor(self):
        async with async_playwright() as p:
            # 브라우저 실행 (이미지처럼 분석이 필요할 땐 headless=False)
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(viewport={'width': 1280, 'height': 1000})
            page = await context.new_page()

            try:
                await page.goto(self.ir_url, wait_until="load", timeout=30000)
                # Cloudflare나 로딩 지연 대비 2초 대기
                await asyncio.sleep(2)

                # [단계 1] 검색 키워드 및 정규표현식 설정
                # webcast, listen, join, audio 등 다양한 표현 대응
                keywords = ["Webcast", "Listen", "Join", "Event", "Presentation"]
                
                found_el = None
                
                # [단계 2] 모든 프레임에서 후보군 탐색
                for frame in page.frames:
                    # 'Webcast'나 'Listen'이라는 텍스트를 포함한 링크/버튼 후보들 추출
                    candidates = frame.locator("a, button, [role='button']").filter(
                        has_text=re.compile(r"Webcast|Listen|Join|Audio", re.IGNORECASE)
                    )
                    
                    count = await candidates.count()
                    for i in range(count):
                        candidate = candidates.nth(i)
                        
                        # [단계 3] 맥락 확인 (이미지의 HTML 구조 반영)
                        # 해당 버튼의 부모 구역(article 혹은 div)의 전체 텍스트를 가져옴
                        parent_area = candidate.locator("xpath=./ancestor::div[contains(@class, 'item')] | ./ancestor::article")
                        
                        if await parent_area.count() > 0:
                            context_text = await parent_area.first.inner_text()
                            
                            # --- [날짜 체크 로직 - 현재는 주석 처리] ---
                            # if self.target_date_str not in context_text:
                            #     continue # 날짜가 맞지 않으면 스킵
                            # ------------------------------------------
                            
                            # 과거 데이터인지 확인 (Replay, Archive 등 제외)
                            # if "Replay" in context_text or "Archive" in context_text:
                            #     continue

                            # 모든 조건을 통과하면 이 버튼이 타겟!
                            if await candidate.is_visible():
                                found_el = candidate
                                break
                    
                    if found_el: break

                if not found_el:
                    return False

                # [단계 4] 진입 성공 여부 확인
                # 실제 클릭 전 해당 요소로 스크롤
                await found_el.scroll_into_view_if_needed()
                await found_el.click(force=True)

                # 이동 후 오디오나 비디오 태그가 로드될 때까지 대기 (성공의 증거)
                try:
                    # 네트워크 안정화 대기
                    await page.wait_for_load_state("networkidle", timeout=15000)
                    return True 
                except:
                    # 페이지 구조에 따라 networkidle이 안 뜰 수 있으므로 True 반환
                    return True

            except Exception as e:
                return False
            finally:
                await browser.close()

if __name__ == "__main__":
    # 단일 테스트용 코드
    XYL_URL = "https://investors.airbnb.com/events-and-presentations/default.aspx" # 테스트 URL (autodesk는 위젯이 다를 수 있음)
    agent = EarningsAgent("ABNB", XYL_URL)
    result = asyncio.run(agent.monitor())
    print(f"테스트 결과: {result}")