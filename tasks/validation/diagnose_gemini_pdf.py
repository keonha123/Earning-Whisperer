"""Run PDF API checks while retaining sanitized provider failure diagnostics."""
from pathlib import Path
import hashlib
import json
import os
import re
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ai-engine"))
from core.gemini_client import GeminiClient
from config import get_settings
from importlib.metadata import version
import test_supplied_pdf


if __name__ == "__main__":
    output = Path(sys.argv[sys.argv.index("--output") + 1]).with_suffix(".provider.json")
    original = GeminiClient._generate_with_modern_sdk
    events = []
    lock = threading.Lock()
    started = time.monotonic()
    def diagnosed(self, model, prompt, config):
        begin = time.monotonic()
        event = {"model": model, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()[:16],
                 "started_seconds": round(begin-started, 3), "prompt_chars": len(prompt),
                 "kind": "translation" if prompt.startswith("Translate") else "verifier" if prompt.startswith("Act as a strict") else "qa" if prompt.startswith("Answer this") else "analysis",
                 "thinking": config.get("thinking_level"), "max_output_tokens": config.get("max_output_tokens")}
        try:
            value = original(self, model, prompt, config)
            event["status"] = "ok"
            if event["kind"] == "translation":
                # This diagnostic uses only the user-supplied public PDF text.
                # Retain the response to explain numeric/grounding rejection.
                event["translation_response"] = str(value[0])[:24000]
            return value
        except Exception as exc:
            message = str(exc)
            for secret in (os.getenv("GEMINI_API_KEY"), get_settings().gemini_api_key):
                if secret:
                    message = message.replace(secret, "[REDACTED]")
            message = re.sub(r"AIza[\w-]+", "[REDACTED]", message)
            event.update(status="error", error_type=type(exc).__name__,
                         status_code=getattr(exc, "code", None), message=message[:800])
            raise
        finally:
            event["elapsed_seconds"] = round(time.monotonic()-begin, 3)
            with lock:
                events.append(event)
                output.write_text(json.dumps({"sdk_version": version("google-genai"), "events": events}, ensure_ascii=False, indent=2), encoding="utf-8")
    GeminiClient._generate_with_modern_sdk = diagnosed
    raise SystemExit(test_supplied_pdf.main())
