"""시연용 근거 뉴스 수집 도구.

정기 수집기(``collectors/news/finnhub_news_job.py``)는 "오늘부터 N일 전"만 조회한다.
시연은 과거의 특정 어닝콜을 재생하므로 **그 콜 주변의 창**을 명시적으로 지정해야 한다.

두 단계로 나눠 놓은 이유가 있다.

1. ``collect`` — Finnhub 에서 받아 JSON 스냅샷으로 떨군다. 스냅샷을 저장소에 두면
   시연 재현에 API 키도 네트워크도 필요 없고, 팀원이 어떤 근거로 판정이 나왔는지
   그대로 열어볼 수 있다.
2. ``ingest`` — 스냅샷을 ai-engine 에 넣는다. 근거 저장소를 비웠을 때 이것만 다시 돌린다.

수집 창에 대한 원칙:
    콜이 끝난 뒤 나온 기사로 콜 발언을 검증하면 순환논증이다. 기사가 그 발언을
    받아쓴 것이기 때문이다. 그래서 기본 창은 [콜일 -30일, 콜일 +1일] 이다.
    콜 당일까지 포함하는 것은, 실적 보도자료와 통신사 속보가 콜 시작 시점에 이미
    공개되어 실시간 시스템도 쓸 수 있는 정보이기 때문이다.

사용 예:
    python -m data_pipeline.tools.demo.collect_demo_evidence collect \\
        --ticker WMT --call-date 2026-08-20 --out data_pipeline/data/demo/wmt-2026q2-news.json
    python -m data_pipeline.tools.demo.collect_demo_evidence ingest \\
        --snapshot data_pipeline/data/demo/wmt-2026q2-news.json
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import json
import logging
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

import httpx

from data_pipeline.collectors.news.article_extractor import ArticleTextExtractor


logger = logging.getLogger("demo-evidence")

FINNHUB_URL = "https://finnhub.io/api/v1/company-news"

#: 기본 UA 로는 일부 매체가 봇으로 보고 차단한다. 원문 본문을 받으려면 브라우저 UA 가 필요하다.
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

#: Finnhub 는 요청당 250건 근처에서 잘린다. 30일을 한 번에 요청하면 조용히 누락되므로
#: 날짜 단위로 쪼개 받는다.
CHUNK_DAYS = 2

#: 차트 자동생성 기사만 내보내는 매체. 본문이 수치 해설이 아니라 지표 나열이라
#: 근거로 쓸 수 없고, 양만 많아 검색을 흐린다.
EXCLUDED_SOURCES = {"chartmill"}


def _finnhub_key() -> str:
    key = os.getenv("FINNHUB_API_KEY", "").strip().strip("'\"")
    if not key:
        raise SystemExit("FINNHUB_API_KEY 가 필요합니다. backend/.env 를 참고하세요.")
    return key


def _fetch_window(client: httpx.Client, ticker: str, start: date, end: date, key: str) -> list[dict[str, Any]]:
    response = client.get(
        FINNHUB_URL,
        params={"symbol": ticker, "from": start.isoformat(), "to": end.isoformat(), "token": key},
    )
    if response.status_code == 429:
        # 한도 초과. 여기서 계속 밀어붙이면 남은 구간까지 전부 실패한다.
        logger.warning("Finnhub 한도 초과 — 20초 대기 후 재시도 %s~%s", start, end)
        time.sleep(20)
        response = client.get(
            FINNHUB_URL,
            params={"symbol": ticker, "from": start.isoformat(), "to": end.isoformat(), "token": key},
        )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else []


def collect(ticker: str, call_date: date, days_before: int, days_after: int, out: Path) -> None:
    key = _finnhub_key()
    start = call_date - timedelta(days=days_before)
    end = call_date + timedelta(days=days_after)

    seen: dict[str, dict[str, Any]] = {}
    dropped_source = 0
    with httpx.Client(timeout=30.0) as client:
        cursor = start
        while cursor <= end:
            chunk_end = min(cursor + timedelta(days=CHUNK_DAYS - 1), end)
            items = _fetch_window(client, ticker, cursor, chunk_end, key)
            for item in items:
                provider_id = str(item.get("id") or "")
                headline = str(item.get("headline") or "").strip()
                published_at = item.get("datetime")
                if not provider_id or not headline or not published_at:
                    continue
                source = str(item.get("source") or "").strip()
                if source.lower() in EXCLUDED_SOURCES:
                    dropped_source += 1
                    continue
                seen[provider_id] = {
                    "provider": "finnhub",
                    "provider_id": provider_id,
                    "ticker": ticker.upper(),
                    "headline": headline,
                    "summary": str(item.get("summary") or "").strip(),
                    "url": str(item.get("url") or "").strip(),
                    "source": source,
                    "published_at": int(published_at),
                    "metadata": {
                        "category": item.get("category") or "",
                        "related": item.get("related") or ticker.upper(),
                    },
                }
            logger.info("%s~%s: 누적 %d건", cursor, chunk_end, len(seen))
            cursor = chunk_end + timedelta(days=1)

    articles = sorted(seen.values(), key=lambda i: i["published_at"])
    snapshot = {
        "ticker": ticker.upper(),
        "call_date": call_date.isoformat(),
        "window": {"from": start.isoformat(), "to": end.isoformat()},
        "collected_at": datetime.now().astimezone().isoformat(),
        "source_counts": _source_counts(articles),
        "dropped_excluded_sources": dropped_source,
        "articles": articles,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("스냅샷 저장: %s (%d건)", out, len(articles))
    for source, count in snapshot["source_counts"].items():
        logger.info("  %-16s %d", source, count)



def enrich(snapshot_path: Path, workers_delay: float) -> None:
    """스냅샷의 기사에 본문을 채운다.

    요약만으로는 근거가 부족하다. Finnhub 요약은 중앙값 146자라 "net sales grew 5%"
    같은 구체적 수치가 대부분 빠져 있고, 그 상태로는 관련도가 0.59 언저리까지 떨어져
    검증 가능한 주장도 근거 부족으로 판정된다. 본문을 넣어야 수치가 검색에 잡힌다.

    Finnhub 의 url 은 리다이렉트이므로 원문 매체로 따라간다. 실패하는 기사는 그냥
    요약만 남는다 — 전체 수집을 멈추지 않는다.
    """
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    articles = snapshot["articles"]
    extractor = ArticleTextExtractor(timeout_seconds=20.0, user_agent=_BROWSER_UA)

    counts: dict[str, int] = {}
    for index, article in enumerate(articles, start=1):
        status = extractor.enrich_item(article)
        counts[status] = counts.get(status, 0) + 1
        if index % 25 == 0:
            logger.info("본문 추출 %d/%d — %s", index, len(articles), counts)
        time.sleep(workers_delay)

    snapshot["content_stats"] = counts
    snapshot["content_chars_median"] = _median_content_chars(articles)
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("본문 추출 완료: %s", counts)
    logger.info("본문 길이 중앙값: %d자", snapshot["content_chars_median"])


def _median_content_chars(articles: list[dict[str, Any]]) -> int:
    lengths = sorted(len(str(a.get("content") or "")) for a in articles if a.get("content"))
    return lengths[len(lengths) // 2] if lengths else 0

def _source_counts(articles: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for article in articles:
        counts[article["source"] or "?"] = counts.get(article["source"] or "?", 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def ingest(
    snapshot_path: Path,
    ai_engine_url: str,
    batch_size: int,
    relevance_terms: list[str],
    max_content_chars: int,
) -> None:
    """스냅샷을 ai-engine 에 인입한다.

    두 가지를 거른다.

    ``relevance_terms`` — Finnhub 의 종목 뉴스 피드에는 그 종목과 무관한 일반 시장
    기사가 절반 가까이 섞여 있다. 그대로 넣으면 검색 정밀도가 떨어진다. 실측에서
    연준 기사가 월마트 발언 검증에 0.72 로 잡혔다. 제목이나 요약에 회사 이름이
    없는 기사는 빼는 편이 낫다.

    ``max_content_chars`` — 기사 본문 전체를 넣으면 청크가 급증해 무료 등급 임베딩
    한도에 걸린다. 실적 기사는 수치가 앞부분에 몰려 있으므로 앞을 남긴다.
    """
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    articles: list[dict[str, Any]] = snapshot["articles"]

    if relevance_terms:
        pattern = re.compile("|".join(re.escape(term) for term in relevance_terms), re.IGNORECASE)
        before = len(articles)
        articles = [
            a for a in articles
            if pattern.search(str(a.get("headline") or "")) or pattern.search(str(a.get("summary") or ""))
        ]
        logger.info("관련도 필터: %d건 → %d건 (제외 %d건)", before, len(articles), before - len(articles))

    if max_content_chars > 0:
        truncated = 0
        for article in articles:
            content = str(article.get("content") or "")
            if len(content) > max_content_chars:
                article["content"] = content[:max_content_chars]
                truncated += 1
        logger.info("본문 상한 %d자 적용: %d건 절단", max_content_chars, truncated)

    accepted = 0
    with httpx.Client(timeout=300.0) as client:
        for start in range(0, len(articles), batch_size):
            batch = articles[start : start + batch_size]
            response = client.post(
                f"{ai_engine_url.rstrip('/')}/api/v1/integration/collector/news",
                json={"items": batch},
            )
            response.raise_for_status()
            body = response.json()
            accepted += int(body.get("accepted_count") or 0)
            logger.info("인입 %d/%d — 누적 accepted=%d", min(start + batch_size, len(articles)), len(articles), accepted)
    logger.info("완료: %d건 요청, accepted=%d", len(articles), accepted)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # httpx 는 요청 URL 을 통째로 INFO 로 찍는다. 토큰이 쿼리스트링에 있으므로
    # 그대로 두면 API 키가 로그와 터미널 기록에 남는다.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    c = sub.add_parser("collect", help="Finnhub 에서 받아 스냅샷으로 저장")
    c.add_argument("--ticker", required=True)
    c.add_argument("--call-date", required=True, help="어닝콜 날짜 (YYYY-MM-DD)")
    c.add_argument("--days-before", type=int, default=30)
    c.add_argument("--days-after", type=int, default=1)
    c.add_argument("--out", required=True, type=Path)

    e = sub.add_parser("enrich", help="스냅샷 기사에 원문 본문을 채운다")
    e.add_argument("--snapshot", required=True, type=Path)
    e.add_argument("--delay", type=float, default=0.3, help="요청 간 간격(초)")

    i = sub.add_parser("ingest", help="스냅샷을 ai-engine 에 인입")
    i.add_argument("--snapshot", required=True, type=Path)
    i.add_argument("--ai-engine-url", default=os.getenv("AI_ENGINE_URL", "http://localhost:8000"))
    i.add_argument("--batch-size", type=int, default=20)
    i.add_argument("--relevance-terms", default="",
                   help="쉼표 구분. 제목/요약에 이 중 하나가 없는 기사는 제외한다.")
    i.add_argument("--max-content-chars", type=int, default=2500,
                   help="기사 본문 상한. 0 이면 자르지 않는다.")

    args = parser.parse_args(argv)
    if args.command == "collect":
        collect(args.ticker, date.fromisoformat(args.call_date), args.days_before, args.days_after, args.out)
    elif args.command == "enrich":
        enrich(args.snapshot, args.delay)
    else:
        ingest(
            args.snapshot,
            args.ai_engine_url,
            args.batch_size,
            [term.strip() for term in args.relevance_terms.split(",") if term.strip()],
            args.max_content_chars,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
