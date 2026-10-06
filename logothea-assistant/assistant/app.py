"""FastAPI 앱. backend 만 부르는 내부 서비스라 X-Internal-Secret 이 맞아야 요청을 받는다."""

from __future__ import annotations

import hmac
import json
import logging
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse

from assistant.classifier import GlossaryProvider
from assistant.clients import AiEngineClient, BackendClient
from assistant.config import Settings, get_settings
from assistant.context import ContextAssembler
from assistant.openai_client import OpenAIClient
from assistant.pipeline import AnswerPipeline, error_event
from assistant.schemas import AskRequest

logger = logging.getLogger(__name__)


class _ClosingStreamingResponse(StreamingResponse):
    """응답이 어떻게 끝나든 생성기를 닫는다. Starlette 는 연결이 끊겨도 body_iterator 를 닫지 않아, 닫히는 시점이 GC 에 맡겨진다."""

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self.body_iterator.aclose()


def format_sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def build_pipeline(settings: Settings) -> tuple[AnswerPipeline, httpx.AsyncClient]:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY 가 설정되지 않았습니다")
    if not settings.internal_secret:
        raise RuntimeError("INTERNAL_SECRET 이 설정되지 않았습니다")
    http = httpx.AsyncClient(timeout=settings.context_timeout_seconds)
    backend = BackendClient(http, base_url=settings.backend_base_url, secret=settings.internal_secret)
    engine = AiEngineClient(http, base_url=settings.ai_engine_base_url)
    llm = OpenAIClient(model=settings.assistant_model, parse_effort=settings.classify_reasoning_effort,
                       stream_effort=settings.generate_reasoning_effort, api_key=settings.openai_api_key,
                       timeout_seconds=settings.openai_timeout_seconds)
    assembler = ContextAssembler(backend, engine, timeout_seconds=settings.context_timeout_seconds,
                                 news_top_k=settings.news_top_k, news_lookback_days=settings.news_lookback_days)
    return AnswerPipeline(llm=llm, assembler=assembler, glossary=GlossaryProvider(backend.glossary)), http


def create_app(settings: Settings | None = None, pipeline: AnswerPipeline | None = None) -> FastAPI:
    settings = settings or get_settings()
    http: httpx.AsyncClient | None = None
    if pipeline is None:
        pipeline, http = build_pipeline(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        if http is not None:
            await http.aclose()

    app = FastAPI(title="logothea-assistant", lifespan=lifespan)

    def require_internal_secret(x_internal_secret: str | None = Header(default=None)) -> None:
        expected = settings.internal_secret
        if not expected or not hmac.compare_digest((x_internal_secret or "").encode(), expected.encode()):
            raise HTTPException(status_code=401, detail="invalid internal secret")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/assistant/ask", dependencies=[Depends(require_internal_secret)])
    async def ask(body: AskRequest) -> StreamingResponse:
        return _ClosingStreamingResponse(_sse_stream(pipeline, body), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app


async def _sse_stream(pipeline: AnswerPipeline, request: AskRequest) -> AsyncIterator[str]:
    try:
        # 클라이언트가 끊겨 Starlette 가 응답 생성을 멈추면 파이프라인 생성기까지 닫혀 LLM 스트림이 정리된다.
        async with aclosing(pipeline.run(request)) as events:
            async for event, data in events:
                yield format_sse(event, data)
    except Exception:
        logger.exception("질의응답 처리 중 예상하지 못한 오류가 났습니다")
        event, data = error_event("internal")
        yield format_sse(event, data)
