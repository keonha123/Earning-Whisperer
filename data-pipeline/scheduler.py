from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from collectors.news import FinnhubCompanyNewsStrategy, FinnhubRateLimitError
from collectors.news.ai_engine_client import AiEngineNewsClient
from collectors.news.config import get_news_settings
from collectors.news.state_store import NewsStateStore


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("finnhub-news-scheduler")


def _doc_key(item: dict) -> str:
    # Finnhub id는 뉴스별 고유값이지만, 추후 다른 뉴스 제공자를 추가할 수 있으므로
    # provider/ticker까지 포함해 중복 제거 키를 안정적으로 만든다.
    return f"{item['provider']}:{item['ticker']}:{item['provider_id']}"


class FinnhubNewsJob:
    def __init__(self) -> None:
        # 설정은 환경변수 기반으로 읽는다. 나중에 M7에서 Nasdaq100으로 확장할 때
        # 코드 수정 없이 ticker 목록만 바꿀 수 있게 하기 위함이다.
        self.settings = get_news_settings()
        self.collector = FinnhubCompanyNewsStrategy(
            api_key=self.settings.finnhub_api_key,
            lookback_days=self.settings.lookback_days,
            timeout_seconds=self.settings.request_timeout_seconds,
        )
        self.ai_engine = AiEngineNewsClient(
            self.settings.ai_engine_url,
            timeout_seconds=self.settings.request_timeout_seconds,
        )
        self.state = NewsStateStore(self.settings.state_path)

    def run_once(self) -> None:
        # 이 메서드가 스케줄러가 반복 실행하는 작업 단위다.
        # APScheduler가 주기적으로 호출하고, 운영 중 프로세스가 재시작될 수 있으므로
        # 같은 뉴스가 다시 들어와도 안전하게 처리되도록 구성한다.
        if not self.settings.finnhub_api_key:
            logger.error("FINNHUB_API_KEY is not configured; skipping news collection")
            return

        logger.info("Collecting Finnhub news for tickers=%s", ",".join(self.settings.tickers))
        try:
            collected = self.collector.collect(self.settings.tickers)
        except FinnhubRateLimitError as exc:
            # 429(rate limit)는 작업 단위에서 처리한다. 같은 실행 안에서 즉시 재시도하면
            # 제한 문제가 더 커질 수 있으므로 다음 스케줄 주기까지 기다린다.
            logger.warning("Finnhub rate limit reached; next scheduled run will retry: %s", exc)
            return
        except Exception:
            logger.exception("Finnhub news collection failed")
            return

        # Finnhub는 날짜 범위로 조회하므로 매번 같은 뉴스가 반복해서 내려올 수 있다.
        # state file에 저장된 처리 이력을 기준으로 새 뉴스만 ai-engine에 보낸다.
        new_items: list[dict] = []
        new_keys: list[str] = []
        for item in collected:
            key = _doc_key(item)
            if self.state.is_seen(key):
                continue
            new_items.append(item)
            new_keys.append(key)

        if not new_items:
            logger.info("No new Finnhub news items found")
            return

        try:
            response = self.ai_engine.ingest_news(new_items)
        except Exception:
            # ai-engine 전달에 실패한 뉴스는 seen 처리하지 않는다.
            # 그래야 다음 실행에서 다시 전달을 시도할 수 있다.
            logger.exception("Failed to deliver Finnhub news to ai-engine")
            return

        # ai-engine이 batch를 정상 수락한 뒤에만 seen 처리한다.
        # Qdrant까지 도달하지 못한 뉴스를 로컬 상태가 숨기지 않게 하기 위함이다.
        self.state.mark_many(new_keys)
        self.state.save()
        logger.info(
            "Delivered %d Finnhub news items to ai-engine: %s",
            len(new_items),
            response,
        )


def main() -> None:
    job = FinnhubNewsJob()
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        job.run_once,
        trigger=IntervalTrigger(minutes=job.settings.interval_minutes),
        id="finnhub_company_news_m7",
        name="Collect Finnhub company news for M7 tickers",
        # 수집 작업이 10분보다 오래 걸려도 같은 작업이 동시에 겹쳐 실행되지 않게 한다.
        max_instances=1,
        # 스케줄러가 잠시 멈추거나 지연됐을 때 밀린 실행들을 여러 번 몰아서 돌리지 않고
        # 한 번으로 합친다.
        coalesce=True,
        replace_existing=True,
    )

    logger.info(
        "Starting Finnhub news scheduler interval=%dm state_path=%s ai_engine_url=%s",
        job.settings.interval_minutes,
        job.settings.state_path,
        job.settings.ai_engine_url,
    )
    # 프로세스 시작 후 첫 10분을 기다리지 않고 즉시 한 번 수집한다.
    job.run_once()
    scheduler.start()


if __name__ == "__main__":
    main()
