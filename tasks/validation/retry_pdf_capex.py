"""Focused real-provider diagnosis after the recorded supplied-PDF failures."""
from pathlib import Path
import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ai-engine"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from dotenv import dotenv_values
    for key, value in dotenv_values(args.env_file).items():
        if key in {"GEMINI_API_KEY", "GEMINI_PRIMARY_MODEL", "GEMINI_MODEL_FAST", "GEMINI_REVIEW_MODEL"} and value:
            os.environ[key] = value
    logging.disable(logging.CRITICAL)
    from pypdf import PdfReader
    text = " ".join(" ".join(page.extract_text() or "" for page in PdfReader(args.pdf).pages).split())
    segment = re.search(r"In fiscal Q1, we project capex.*?approximately \$25 billion\.", text).group()
    from config import Settings
    from models.transcript_assistant_models import TranscriptTranslateRequest, TranscriptAskRequest
    from services.transcript_assistant_service import TranscriptAssistantService
    from core.gemini_client import gemini_client
    from datetime import datetime, UTC
    report = {"kind": "focused_retry_after_failed_default_run", "source": segment,
              "limitations": ["Selected PDF segment only; no external corpus in this focused diagnosis",
                              "Original full-run failures remain recorded in pdf-micron-20261002.json"], "checks": {}}
    provider_errors = []
    generate_sdk = gemini_client._generate_with_modern_sdk
    def diagnosed_sdk(*values):
        try:
            return generate_sdk(*values)
        except Exception as exc:
            status = getattr(exc, "code", None)
            provider_errors.append({"error_type": type(exc).__name__, "status_code": status if isinstance(status, int) else None})
            raise
    gemini_client._generate_with_modern_sdk = diagnosed_sdk
    async def run():
        service = TranscriptAssistantService(Settings(_env_file=None))
        generate = service._generate
        trace = []
        async def traced(prompt, timeout):
            try:
                value = await generate(prompt, timeout)
                trace.append({"output": value})
                return value
            except Exception as exc:
                trace.append({"error_type": type(exc).__name__})
                raise
        service._generate = traced
        identity = {"ticker": "MU", "call_id": "supplied_pdf:MU:mu-fy26q4"}
        async def capture(name, action):
            trace.clear()
            start = time.monotonic()
            result = await action
            report["checks"][name] = {"response": result.model_dump(mode="json"),
                "elapsed_seconds": round(time.monotonic()-start, 3), "provider_diagnostics": list(trace)}
            report["provider_errors"] = list(provider_errors)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
        await capture("translation_default_8s", service.translate(TranscriptTranslateRequest(**identity, sequence=0, text=segment)))
        request = TranscriptAskRequest(**identity, segment_sequences=[0], segment_texts=[segment],
            question="회계연도 1분기와 상반기 설비투자 전망은 각각 얼마인가요?", as_of=datetime(2026, 10, 1, 12, tzinfo=UTC))
        result = await capture("qa_default_12s", service.ask(request))
        if not result.available:
            service.settings.transcript_qa_timeout_seconds = 30
            await capture("qa_configured_30s", service.ask(request))
    asyncio.run(run())
    print(json.dumps({name: {"available": check["response"]["available"], "elapsed_seconds": check["elapsed_seconds"],
        "warnings": check["response"]["warnings"]} for name, check in report["checks"].items()}))


if __name__ == "__main__":
    main()
