"""Current-candidate document/API verification; no broker or publication calls.

PDF prose is input evidence, never execution instructions. Full results stay ignored.
"""
from pathlib import Path
import argparse
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ai-engine"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from dotenv import dotenv_values
    for key, value in dotenv_values(args.env_file).items():
        if key in {"GEMINI_API_KEY", "GEMINI_PRIMARY_MODEL", "GEMINI_MODEL_FAST", "GEMINI_REVIEW_MODEL"} and value:
            os.environ[key] = value
    logging.disable(logging.CRITICAL)
    from pypdf import PdfReader
    raw = args.pdf.read_bytes()
    pages = [page.extract_text() or "" for page in PdfReader(args.pdf).pages]
    text = "\n\n".join(page.strip() for page in pages if page.strip())
    normalized = " ".join(text.split())
    revenue = re.search(r"Consolidated fiscal Q4 revenue was .*?year over year\.", normalized).group()
    capex = re.search(r"In fiscal Q1, we project capex.*?approximately \$25 billion\.", normalized).group()
    tail = "We will now open for questions."
    report = {
        "source": {"path": str(args.pdf), "sha256": hashlib.sha256(raw).hexdigest(),
                   "page_count": len(pages), "character_count": len(text), "ticker": "MU",
                   "printed_date": "2026-09-30", "kind": "supplied_prepared_remarks_not_video_transcript",
                   "external_authentication": "not_performed", "analyst_qa_present": False},
        "limitations": ["No audio/STT/backend/Electron path", "Source claims not independently verified",
                        "Hash embeddings for full local Qdrant indexing; real Gemini embeddings tested separately",
                        "Heuristic phase1, unavailable runtime-control DB intentionally blocks execution",
                        "No previous-quarter transcript supplied", "No market prices or broker calls"],
        "checks": {}, "assertions": {},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    def check(name, condition):
        report["assertions"][name] = bool(condition)
        save()
    (args.output.parent / "supplied-pdf-text.txt").write_text(text, encoding="utf-8")
    check("all_ten_pages_nonempty", len(pages) == 10 and all(page.strip() for page in pages))
    check("source_company_and_final_line", "Micron Technology" in pages[0] and tail in pages[-1])
    try:
        import fitz
        with fitz.open(args.pdf) as pdf:
            for index in (0, 6, 8, 9):
                pdf[index].get_pixmap(matrix=fitz.Matrix(1, 1)).save(str(args.output.parent / f"pdf-page-{index+1}.png"))
        report["visual_review_pages"] = [1, 7, 9, 10]
    except ImportError:
        report["visual_review_pages"] = "renderer_unavailable"
    with tempfile.TemporaryDirectory(prefix="ew-pdf-test-") as tmp:
        os.environ.update({
            "VECTOR_STORE_BACKEND": "qdrant", "QDRANT_URL": "", "QDRANT_PATH": tmp + "/vectors",
            "EMBEDDING_PROVIDER": "hash", "EMBEDDING_DIMENSION": "256",
            "EXTERNAL_EMBEDDING_PROVIDER": "hash", "EXTERNAL_EMBEDDING_DIMENSION": "256",
            "EVIDENCE_POSTGRES_ENABLED": "false", "EVIDENCE_AUTO_BOOTSTRAP": "false",
            "PHASE1_PROVIDER": "heuristic", "PHASE1_WARMUP_ON_STARTUP": "false",
            "LEGACY_REDIS_PUBLISH_ENABLED": "false", "REDIS_ENRICHED_PUBLISH_ENABLED": "false",
            "REDIS_PROFILE_PUBLISH_ENABLED": "false", "LIVE_SESSION_REDIS_PUBLISH_ENABLED": "false",
            "EVIDENCE_SYNC_ENABLED": "false", "RUNTIME_CONTROLS_MODE": "required",
            "DATABASE_URL": "postgresql://unused:unused@127.0.0.1:15439/unused",
            "COMPANY_INTELLIGENCE_STORE_PATH": tmp + "/companies.json",
            "LIVE_SESSION_STORE_PATH": tmp + "/sessions", "REDIS_RETRY_SPOOL_PATH": tmp + "/retry.jsonl",
        })
        from config import get_settings
        get_settings.cache_clear()
        from fastapi.testclient import TestClient
        # main initializes its module-level app. Reuse it to avoid opening the
        # same local Qdrant directory a second time in this isolated process.
        from main import app
        def capture(client, name, route, payload=None, **kwargs):
            started = time.monotonic()
            try:
                response = client.post(route, json=payload, **kwargs) if payload is not None else client.post(route, **kwargs)
                body = response.json()
                report["checks"][name] = {"status_code": response.status_code,
                    "elapsed_seconds": round(time.monotonic()-started, 3), "response": body}
                print(json.dumps({"check": name, "status_code": response.status_code}), flush=True)
                save()
                return body
            except Exception as exc:
                report["checks"][name] = {"error_type": type(exc).__name__, "elapsed_seconds": round(time.monotonic()-started, 3)}
                save()
                return {}
        with TestClient(app) as client:
            upload = capture(client, "pdf_upload", "/v1/engine/transcripts/upload",
                files={"file": (args.pdf.name, raw, "application/pdf")},
                data={"ticker": "MU", "title": "Supplied Micron FY2026 Q4 prepared remarks",
                      "published_at": "2026-09-30T23:59:59+00:00"})
            check("upload_preserves_all_text", upload.get("page_count") == 10 and upload.get("character_count") == len(text))
            check("upload_stored_and_indexed", upload.get("accepted", 0) > 0 and upload.get("persisted") == upload.get("accepted")
                  and upload.get("vector_upserted") == upload.get("accepted") and not upload.get("warnings"))
            corpus = capture(client, "collector_transcript", "/api/v1/integration/collector/earnings-transcripts", {
                "items": [{"provider": "supplied_pdf", "provider_id": "mu-fy26q4", "ticker": "MU",
                "title": "Supplied Micron FY2026 Q4 prepared remarks", "content": text,
                "published_at": "2026-09-30T23:59:59Z", "fiscal_quarter": "Q4_FY2026",
                "metadata": {"call_id": "supplied_pdf:MU:mu-fy26q4", "input_kind": "prepared_remarks"}}]})
            check("collector_accepted", corpus.get("accepted_count") == 1)
            if corpus.get("document_ids"):
                hits = app.state.transcript_repository.search_prior_transcript_chunks(
                    ticker="MU", document_id=corpus["document_ids"][0], query=tail, top_k=5)
                report["tail_retrieval"] = [hit.model_dump(mode="json") for hit in hits]
                check("final_sentence_searchable", any(tail in hit.snippet for hit in hits))
                points, _ = app.state.transcript_repository.client.scroll(
                    collection_name=app.state.settings.qdrant_transcript_collection_name, limit=1000, with_vectors=False)
                report["transcript_point_count"] = len(points)
                check("full_document_split_into_multiple_chunks", len(points) > 1)
            identity = {"ticker": "MU", "call_id": "supplied_pdf:MU:mu-fy26q4", "sequence": 0}
            for name, segment in (("revenue", revenue), ("capex", capex)):
                translation = capture(client, "translation_"+name, "/v1/engine/transcript/translate", {**identity, "text": segment})
                check("translation_"+name+"_available", translation.get("available") is True and bool(translation.get("text_ko")))
                check("translation_"+name+"_identity", translation.get("original_text") == segment and translation.get("call_id") == identity["call_id"])
                question = "이번 분기 매출과 전년 대비 증가율은 얼마인가요?" if name == "revenue" else "회계연도 1분기와 상반기 설비투자 전망은 각각 얼마인가요?"
                answer = capture(client, "qa_"+name, "/v1/engine/transcript/ask", {
                    "ticker": "MU", "call_id": identity["call_id"], "segment_sequences": [0],
                    "segment_texts": [segment], "question": question, "as_of": "2026-10-01T12:00:00Z"})
                check("qa_"+name+"_available", answer.get("available") is True and bool(answer.get("answer_ko")))
                evidence = answer.get("evidence", [])
                check("qa_"+name+"_exact_citations", bool(answer.get("citations")) and all(
                    c["evidence_index"] < len(evidence) and c["quote"] in evidence[c["evidence_index"]]["snippet"]
                    for c in answer.get("citations", [])))
            prior = capture(client, "qa_previous_quarter_missing", "/v1/engine/transcript/ask", {
                "ticker": "MU", "call_id": identity["call_id"], "segment_sequences": [0], "segment_texts": [revenue],
                "question": "지난 분기 콜과 비교해 매출 가이던스가 어떻게 달라졌나요?", "as_of": "2026-10-01T12:00:00Z"})
            check("missing_prior_not_invented", prior.get("available") is False and prior.get("refusal_reason") == "insufficient")
            summary = capture(client, "report", "/v1/engine/earnings/intelligence", {"ticker": "MU", "event_text": revenue + " " + capex})
            check("report_has_source_evidence", summary.get("evidence_count", 0) > 0)
            analysis = capture(client, "analysis", "/api/v1/analyze", {
                "ticker": "MU", "text_chunk": revenue + " " + capex, "timestamp": 1790865600,
                "sequence": 0, "is_final": True, "route_profile": "economy"})
            check("analysis_execution_blocked", analysis.get("execution_allowed") is False and analysis.get("redis_published") is False)
            check("analysis_has_provider_result", bool(analysis.get("rationale")) and "fallback" not in analysis.get("rationale", "").lower())
            start = capture(client, "session_start", "/v1/engine/live-sessions", {
                "ticker": "MU", "call_title": "Supplied PDF verification", "expected_fact_count": 2,
                "execution_mode": "MANUAL", "publish_final_signal": False})
            if start.get("session_id"):
                final = capture(client, "final_signal", "/v1/engine/live-sessions/"+start["session_id"]+"/chunks", {
                    "text": revenue + " " + capex, "sequence": 0, "is_final": True, "route_profile": "economy"})
                check("final_execution_and_delivery_blocked", final.get("final_signal", {}).get("execution_allowed") is False
                    and final.get("redis_delivery", {}).get("attempted") is False)
            from core.external_retriever import GeminiEmbeddingProvider
            started = time.monotonic()
            try:
                vectors = GeminiEmbeddingProvider(model="gemini-embedding-001", dimension=768).embed_texts([revenue, capex, tail])
                report["gemini_document_embeddings"] = {"elapsed_seconds": round(time.monotonic()-started, 3),
                    "count": len(vectors), "dimensions": [len(vector) for vector in vectors]}
                check("real_document_embeddings", len(vectors) == 3 and all(len(vector) == 768 for vector in vectors))
            except Exception as exc:
                report["gemini_document_embeddings"] = {"error_type": type(exc).__name__}
                check("real_document_embeddings", False)
    report["status"] = "passed" if all(report["assertions"].values()) else "failed"
    save()
    print(json.dumps({"status": report["status"], "assertions": report["assertions"]}), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
