"""Compatibility validator for the packaged AI engine.

Run with: python tools/validate_compatibility.py
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CHECKS: list[tuple[str, callable]] = []


def check(name: str):
    def decorator(fn):
        CHECKS.append((name, fn))
        return fn
    return decorator


def _stub_heavy_deps() -> None:
    for mod in ["torch", "transformers", "librosa", "soundfile", "faiss"]:
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)
    torch_mod = sys.modules["torch"]
    if not hasattr(torch_mod, "cuda"):
        torch_mod.cuda = types.SimpleNamespace(is_available=lambda: False)  # type: ignore[attr-defined]


@check("core.gemini_client importable")
def _check_gemini_client_import() -> None:
    _stub_heavy_deps()
    sys.path.insert(0, str(ROOT))
    mod = importlib.import_module("ai_engine.core.gemini_client")
    assert hasattr(mod, "GeminiClient")
    assert hasattr(mod, "gemini_client")


@check("core.five_gate_filter importable")
def _check_five_gate_import() -> None:
    _stub_heavy_deps()
    sys.path.insert(0, str(ROOT))
    mod = importlib.import_module("ai_engine.core.five_gate_filter")
    assert hasattr(mod, "FiveGateFilter")


@check("legacy services re-export stubs match core symbols")
def _check_reexport_stubs() -> None:
    _stub_heavy_deps()
    sys.path.insert(0, str(ROOT))
    pairs = [
        ("ai_engine.core.alpha_formula_engine", "ai_engine.services.alpha_formula_engine"),
        ("ai_engine.core.redis_publisher", "ai_engine.services.redis_publisher"),
    ]
    for core_path, svc_path in pairs:
        core_mod = importlib.import_module(core_path)
        svc_mod = importlib.import_module(svc_path)
        core_pub = {n for n in dir(core_mod) if not n.startswith("_")}
        svc_pub = {n for n in dir(svc_mod) if not n.startswith("_")}
        missing = core_pub - svc_pub - {"annotations"}
        assert not missing, f"{svc_path} missing symbols from core: {missing}"


@check("config defaults: primary/review models set to Gemini 3.1 preview family")
def _check_models() -> None:
    _stub_heavy_deps()
    sys.path.insert(0, str(ROOT))
    from ai_engine import config as cfg_module
    settings = cfg_module.Settings(gemini_api_key="test-key", _env_file=None)
    assert settings.gemini_primary_model == "gemini-3.1-flash-preview"
    assert settings.gemini_review_model == "gemini-3.1-pro-preview"


@check("config defaults: base formula weights are positive")
def _check_weights() -> None:
    _stub_heavy_deps()
    sys.path.insert(0, str(ROOT))
    from ai_engine import config as cfg_module
    settings = cfg_module.Settings(gemini_api_key="test-key", _env_file=None)
    weights = [settings.w_sentiment, settings.w_sue, settings.w_momentum, settings.w_volume]
    assert all(weight > 0 for weight in weights)


@check("config defaults: app_version starts with 9.")
def _check_app_version() -> None:
    _stub_heavy_deps()
    sys.path.insert(0, str(ROOT))
    from ai_engine import config as cfg_module
    settings = cfg_module.Settings(gemini_api_key="test-key", _env_file=None)
    assert settings.app_version.startswith("9.")


@check("repo hygiene files exist")
def _check_hygiene() -> None:
    root = Path(__file__).resolve().parent.parent
    gi = root / ".gitignore"
    data_dir = root / "data"
    assert gi.exists(), ".gitignore not found"
    text = gi.read_text(encoding="utf-8")
    assert "__pycache__/" in text
    assert ".env" in text
    assert data_dir.exists(), "data directory missing"
    assert (data_dir / ".gitkeep").exists(), "data/.gitkeep missing"
    assert not list(data_dir.glob("*.json")), "data/ should not contain committed json artifacts"


def main() -> int:
    print("EarningWhisperer Compatibility Validator — v9")
    print("=" * 60)
    passed = 0
    failed = 0
    for name, fn in CHECKS:
        try:
            fn()
            print(f"  ✅  {name}")
            passed += 1
        except Exception as exc:
            print(f"  ❌  {name}")
            print(f"      {exc}")
            failed += 1
    print("=" * 60)
    print(f"Result: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
