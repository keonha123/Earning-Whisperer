from .base import StreamLinkCollector

class YouTubeLiveStrategy(StreamLinkCollector):
    def collect(self, ticker: str) -> str:
        # 여기에 나중에 유튜브 API 검색 로직을 구현합니다.
        # 지금은 테스트를 위해 가짜 주소를 반환합니다.
        return f"https://www.youtube.com/results?search_query={ticker}+earnings+call+live"