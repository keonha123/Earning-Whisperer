import os
from googleapiclient.discovery import build
from .base import StreamLinkCollector
from typing import Optional

class YouTubeLiveStrategy(StreamLinkCollector):
    def __init__(self):
        self.api_key = os.getenv("YOUTUBE_API_KEY")
        self.youtube = build("youtube", "v3", developerKey=self.api_key)

    def collect(self, ticker: str, company_name: str = "") -> Optional[str]:
        """
        유튜브에서 해당 종목의 실시간 어닝콜 스트리밍을 검색하여 URL을 반환합니다.
        """
        # 1. 정교한 검색 쿼리 생성
        search_query = f"{ticker} {company_name} earnings call live"
        print(f"🔍 [YouTube] '{search_query}' 검색 중...")

        try:
            # 2. API 호출: 실시간(live) 혹은 예약된(upcoming) 영상만 검색
            request = self.youtube.search().list(
                q=search_query,
                part="snippet",
                type="video",
                eventType="live",  # 현재 라이브 중인 것 우선
                maxResults=1
            )
            response = request.execute()

            # 3. 라이브가 없다면 예약된(upcoming) 영상 다시 검색
            if not response.get("items"):
                request = self.youtube.search().list(
                    q=search_query,
                    part="snippet",
                    type="video",
                    eventType="upcoming",
                    maxResults=1
                )
                response = request.execute()

            # 4. 결과 처리
            if response.get("items"):
                video_id = response["items"][0]["id"]["videoId"]
                video_title = response["items"][0]["snippet"]["title"]
                print(f"✅ [YouTube] 검색 성공: {video_title}")
                return f"https://www.youtube.com/watch?v={video_id}"
            
            print(f"⚠️ [YouTube] {ticker} 관련 실시간 방송을 찾을 수 없습니다.")
            return None

        except Exception as e:
            print(f"❌ [YouTube] API 호출 중 오류 발생: {e}")
            return None