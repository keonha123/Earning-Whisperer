import argparse
import os
import sys
import requests
import json
from pathlib import Path
from dotenv import dotenv_values

try:
    from ... import database
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import database


DATA_PIPELINE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = DATA_PIPELINE_ROOT.parent


def _load_env():
    # Local .env values override repository defaults, but never Docker/shell values.
    values = {
        **dotenv_values(REPO_ROOT / ".env"),
        **dotenv_values(DATA_PIPELINE_ROOT / ".env"),
    }
    for key, value in values.items():
        if value is not None:
            os.environ.setdefault(key, value)


_load_env()

class IRDiscovery:
    def __init__(self):
        self.api_key = os.getenv("SERPER_API_KEY")
        self.url = "https://google.serper.dev/search"

    def search_ir_page(self, company_name, ticker):
        if not self.api_key:
            print("SERPER_API_KEY가 설정되지 않았습니다.")
            return None

        # 쿼리를 정교하게 짭니다. "기업명 Investor Relations Events Webcast"
        query = f"{company_name} ({ticker}) Investor Relations Events Webcast"
        
        payload = json.dumps({"q": query})
        headers = {
            'X-API-KEY': self.api_key,
            'Content-Type': 'application/json'
        }

        try:
            response = requests.request("POST", self.url, headers=headers, data=payload, timeout=20)
            response.raise_for_status()
            results = response.json()
            
            # 검색 결과 중 가장 신뢰도 높은 상위 링크 반환
            if "organic" in results and len(results["organic"]) > 0:
                return results["organic"][0]["link"]
        except Exception as e:
            print(f"{ticker} 검색 중 오류: {e}")
        return None

    def run_discovery(self, limit: int | None = None, missing_only: bool = False):
        if not self.api_key:
            print("SERPER_API_KEY가 없어 discovery를 실행할 수 없습니다.")
            return

        stocks = database.get_all_stocks()
        if missing_only:
            stocks = [stock for stock in stocks if not stock.get("ir_url")]
        if limit is not None:
            stocks = stocks[:limit]
        
        discovered_count = 0
        for stock in stocks:
            company_name = stock.get("company_name", "")
            ticker = stock.get("ticker", "")
            print(f"{ticker} ({company_name}) 탐색 중...")
            url = self.search_ir_page(company_name, ticker)
            
            if url:
                database.update_stock_ir_url(ticker, url)
                discovered_count += 1
                print(f"발견: {url}")

        print(f"총 {discovered_count}개 기업의 IR 페이지 주소를 확보했습니다.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Discover company IR page URLs.")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N stocks.")
    parser.add_argument(
        "--missing-only",
        action="store_true",
        help="Skip stocks that already have ir_url in the database.",
    )
    args = parser.parse_args()

    discovery = IRDiscovery()
    discovery.run_discovery(limit=args.limit, missing_only=args.missing_only)
