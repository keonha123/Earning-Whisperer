# ═══════════════════════════════════════════════════════════════════════════
# core/gemini_client.py
# Gemini 3 Flash 클라이언트
#
# ⚠️  Gemini 3 주요 변경사항 (2.x와 다름):
#   1. 모델명: gemini-3-flash-preview
#   2. temperature 낮게 설정 금지 → 루프/성능 저하 유발
#      대신 thinking_level="minimal" 로 일관된 출력 유도
#   3. Thought signatures: 멀티턴 대화 시 필수 반환
#   4. SDK: google-genai (from google import genai)
# ═══════════════════════════════════════════════════════════════════════════
import json
import re
import asyncio
import logging
from typing import Optional

from google import genai
from google.genai import types

from models.signal_models import GeminiAnalysisResult
from core.prompt_builder import SYSTEM_PROMPT
from config import settings

logger = logging.getLogger("gemini_client")


class GeminiClient:
    def __init__(self):
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model  = settings.gemini_model          # "gemini-3-flash-preview"

        # ── Gemini 3 생성 설정 ─────────────────────────────────────────────
        # ⚠️  temperature 미설정 (Gemini 3 기본값 1.0 사용)
        #     낮게 설정하면 루프/성능 저하 → 공식 문서 권고사항
        # thinking_level="minimal": 빠른 응답 + 일관된 JSON 구조화 출력
        self.gen_config = types.GenerateContentConfig(
            system_instruction = SYSTEM_PROMPT,
            max_output_tokens  = settings.gemini_max_tokens,
            response_mime_type = "application/json",
            thinking_config    = types.ThinkingConfig(
                thinking_level = settings.gemini_thinking_level  # "minimal"
            ),
        )

    async def analyze(self, user_prompt: str) -> GeminiAnalysisResult:
        """
        Gemini 3 Flash 호출 → GeminiAnalysisResult 반환.
        재시도 3회 (지수 백오프: 1.5s → 3.0s → 4.5s).
        """
        last_error = None
        raw = ""

        for attempt in range(3):
            try:
                response = await asyncio.to_thread(
                    self.client.models.generate_content,
                    model    = self.model,
                    contents = user_prompt,
                    config   = self.gen_config,
                )

                raw = response.text.strip() if response.text else ""

                # 마크다운 코드블록 제거
                raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
                raw = re.sub(r"\s*```$",          "", raw, flags=re.MULTILINE)
                raw = raw.strip()

                if not raw:
                    raise ValueError("Gemini 응답이 비어있음")

                data   = json.loads(raw)
                result = GeminiAnalysisResult(**data)

                logger.info(
                    f"Gemini 분석 완료: direction={result.direction} "
                    f"magnitude={result.magnitude:.2f} "
                    f"confidence={result.confidence:.2f} "
                    f"catalyst={result.catalyst_type} "
                    f"whisper={result.whisper_signal}"
                )
                return result

            except json.JSONDecodeError as e:
                logger.warning(f"JSON 파싱 실패 (시도 {attempt+1}/3): {e}")
                logger.debug(f"원본 응답 (300자): {raw[:300]}")
                last_error = e
            except Exception as e:
                logger.warning(f"Gemini 호출 실패 (시도 {attempt+1}/3): {type(e).__name__}: {e}")
                last_error = e

            if attempt < 2:
                wait = 1.5 * (attempt + 1)
                logger.info(f"{wait:.1f}초 후 재시도...")
                await asyncio.sleep(wait)

        raise RuntimeError(f"Gemini API 3회 모두 실패: {last_error}")


# 싱글턴
gemini_client = GeminiClient()
