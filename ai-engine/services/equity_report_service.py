"""Structured equity report generation for frontend rendering."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
import json
import re
from typing import Any

from pydantic import ValidationError

try:
    from config import Settings, get_settings
    from core.gemini_client import gemini_client
    from core.token_budgeter import TokenBudgeter, TokenUsageEvent
    from models.equity_report_models import (
        EquityReportDataQuality,
        EquityReportRequest,
        EquityReportResponse,
        EquityReportSource,
        ResearchRatingBox,
        ResearchScenario,
        ResearchSection,
        ResearchTable,
        StructuredEquityReport,
    )
except ImportError:  # pragma: no cover
    from ..config import Settings, get_settings
    from ..core.gemini_client import gemini_client
    from ..core.token_budgeter import TokenBudgeter, TokenUsageEvent
    from ..models.equity_report_models import (
        EquityReportDataQuality,
        EquityReportRequest,
        EquityReportResponse,
        EquityReportSource,
        ResearchRatingBox,
        ResearchScenario,
        ResearchSection,
        ResearchTable,
        StructuredEquityReport,
    )


MarketDataProvider = Callable[[str], dict[str, Any]]


class EquityResearchReportService:
    """Produces validated structured equity reports plus derived Markdown.

    The structured object is the source of truth for frontend cards, tables,
    badges, and section navigation. Markdown is derived from the same object for
    compatibility with quick renderers.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        llm_client: Any | None = None,
        market_data_provider: MarketDataProvider | None = None,
        token_budgeter: TokenBudgeter | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm_client = llm_client or gemini_client
        self.market_data_provider = market_data_provider or self._load_yfinance_snapshot
        self.token_budgeter = token_budgeter or TokenBudgeter(self.settings)

    async def generate_report(self, request: EquityReportRequest) -> EquityReportResponse:
        """Generate a validated frontend-ready report for a ticker."""

        generated_at = datetime.now(UTC)
        missing_items: list[str] = []
        warnings: list[str] = []
        market_snapshot: dict[str, Any] = {}
        fallback_used = False

        try:
            market_snapshot = await asyncio.to_thread(self.market_data_provider, request.ticker)
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            warnings.append(f"market_data_lookup_failed: {exc}")
            missing_items.append("market_data")

        if not market_snapshot:
            missing_items.append("market_data")

        model = self._select_model()
        prompt = self._build_structured_prompt(request=request, market_snapshot=market_snapshot)
        config = {
            "route_profile": "review",
            "system_instruction": (
                "You are an institutional-grade senior equity research analyst. "
                "Return only valid JSON matching the requested schema. "
                "Do not claim to represent any bank or broker."
            ),
            "response_mime_type": "application/json",
            "max_output_tokens": int(getattr(self.settings, "gemini_max_tokens", 2048) or 2048),
            "thinking_level": getattr(self.settings, "gemini_review_thinking_level", "medium"),
        }

        prompt_tokens = 0
        output_tokens = 0
        estimated_cost_usd = 0.0
        structured_report: StructuredEquityReport | None = None

        try:
            usage = await self.llm_client.generate_content_with_metadata(model=model, contents=prompt, config=config)
            raw_text = str(getattr(usage, "text", "") or "").strip()
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
            estimated_cost_usd = float(getattr(usage, "estimated_cost_usd", 0.0) or 0.0)
            structured_report = self._parse_structured_response(raw_text)
            self.token_budgeter.record(
                TokenUsageEvent(
                    route_profile="review",
                    model=model,
                    prompt_tokens=prompt_tokens,
                    output_tokens=output_tokens,
                    total_tokens=int(getattr(usage, "total_tokens", 0) or prompt_tokens + output_tokens),
                    estimated_cost_usd=estimated_cost_usd,
                    cached=bool(getattr(usage, "cached", False)),
                    coalesced=bool(getattr(usage, "coalesced", False)),
                    budget_tokens=self.token_budgeter.prompt_budget("review"),
                )
            )
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            warnings.append(f"llm_schema_validation_failed: {exc}")
        except Exception as exc:
            warnings.append(f"llm_generation_failed: {exc}")

        if structured_report is None:
            fallback_used = True
            structured_report = self._fallback_structured_report(request=request, market_snapshot=market_snapshot)
            if not any(item.startswith("llm_") for item in warnings):
                warnings.append("llm_response_empty")

        report_markdown = self._structured_to_markdown(structured_report)

        return EquityReportResponse(
            ticker=request.ticker,
            company_name=self._string_value(market_snapshot, "company_name") or structured_report.rating_box.company_name,
            generated_at=generated_at,
            language=request.language,
            output_format=request.output_format,
            structured_report=structured_report,
            report_markdown=report_markdown,
            sources=self._sources_for(request.ticker, market_snapshot),
            data_quality=EquityReportDataQuality(
                freshness="live_or_recent" if market_snapshot else "fallback_only",
                missing_items=sorted(set(missing_items + structured_report.data_gaps)),
                warnings=warnings,
            ),
            market_snapshot=market_snapshot,
            model=model,
            model_route="review",
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=estimated_cost_usd,
            fallback_used=fallback_used,
        )

    def _select_model(self) -> str:
        return (
            self.settings.gemini_review_model
            or self.settings.gemini_primary_model
            or self.settings.gemini_model_fast
            or "gemini-3.1-pro-preview"
        )

    def _build_structured_prompt(self, *, request: EquityReportRequest, market_snapshot: dict[str, Any]) -> str:
        concerns = request.concerns or "valuation, growth sustainability, profitability, balance sheet risk, catalysts, downside risk"
        facts = self._format_market_snapshot(market_snapshot)
        language = "Korean" if request.language == "ko" else "English"
        return f"""
Stock ticker: {request.ticker}
Specific concerns/questions: {concerns}
Output language: {language}

Known market/data snapshot:
{facts}

Return ONLY valid JSON. Do not wrap in Markdown fences. Use this exact top-level shape:
{{
  "rating_box": {{
    "ticker": "{request.ticker}",
    "company_name": "string or null",
    "current_price": "string or null",
    "market_cap": "string or null",
    "rating": "Buy|Hold|Avoid",
    "conviction": "Low|Medium|High",
    "base_case_price_target": "string or null",
    "bull_case_price_target": "string or null",
    "bear_case_price_target": "string or null",
    "expected_upside_downside": "string or null",
    "key_thesis": ["3 concise bullets"]
  }},
  "sections": [
    {{
      "id": "business_model",
      "title": "Business Model Breakdown",
      "summary": "string",
      "bullets": ["string"],
      "tables": [{{"title": "string", "columns": ["col"], "rows": [["cell"]]}}]
    }}
  ],
  "key_catalysts": ["string"],
  "key_risks": ["string"],
  "scenarios": [
    {{"case": "bull", "thesis": "string", "assumptions": ["string"], "price_target": "string", "probability": "string"}},
    {{"case": "base", "thesis": "string", "assumptions": ["string"], "price_target": "string", "probability": "string"}},
    {{"case": "bear", "thesis": "string", "assumptions": ["string"], "price_target": "string", "probability": "string"}}
  ],
  "final_verdict": "string",
  "analyst_assumptions": ["string"],
  "data_gaps": ["string"]
}}

Required sections:
- business_model
- revenue_streams
- profitability
- balance_sheet
- free_cash_flow
- moat_scorecard
- management_quality
- valuation_snapshot
- peer_comparison
- catalysts
- risks
- bull_case
- bear_case
- base_case
- final_verdict

Rules:
- Use tables for revenue streams, profitability, valuation, peer comparison, and moat scorecard.
- If a number is unavailable, write "N/A" and add a concise item to data_gaps.
- Separate facts from assumptions and analyst judgment.
- Cite source names in text when available, especially yfinance and company filings placeholders.
- Avoid hype and avoid overstating certainty.
""".strip()

    @staticmethod
    def _format_market_snapshot(snapshot: dict[str, Any]) -> str:
        if not snapshot:
            return "- No live market snapshot was available. The report must disclose missing exact figures."
        lines = []
        for key in sorted(snapshot):
            value = snapshot[key]
            if value is None or value == "":
                continue
            lines.append(f"- {key}: {value}")
        return "\n".join(lines) if lines else "- No reliable fields were available."

    def _parse_structured_response(self, raw_text: str) -> StructuredEquityReport:
        if not raw_text:
            raise ValueError("empty LLM response")
        json_text = self._extract_json(raw_text)
        payload = json.loads(json_text)
        if isinstance(payload, dict) and "structured_report" in payload:
            payload = payload["structured_report"]
        if not isinstance(payload, dict):
            raise ValueError("LLM response must be a JSON object")
        return StructuredEquityReport.model_validate(payload)

    @staticmethod
    def _extract_json(raw_text: str) -> str:
        text = raw_text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)
        if text.startswith("{") and text.endswith("}"):
            return text
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return text[start : end + 1]
        return text

    def _fallback_structured_report(
        self,
        *,
        request: EquityReportRequest,
        market_snapshot: dict[str, Any],
    ) -> StructuredEquityReport:
        company = self._string_value(market_snapshot, "company_name") or request.ticker
        current_price = self._string_value(market_snapshot, "current_price")
        market_cap = self._string_value(market_snapshot, "market_cap")
        concerns = request.concerns or "추가 우려사항 없음"
        gaps = ["latest_filings", "segment_financials", "consensus_estimates"]
        if not market_snapshot:
            gaps.append("market_data")

        return StructuredEquityReport(
            rating_box=ResearchRatingBox(
                ticker=request.ticker,
                company_name=company,
                current_price=current_price or "N/A",
                market_cap=market_cap or "N/A",
                rating="Hold",
                conviction="Low",
                base_case_price_target="N/A",
                bull_case_price_target="N/A",
                bear_case_price_target="N/A",
                expected_upside_downside="N/A",
                key_thesis=[
                    "Gemini 또는 핵심 재무 데이터 검증이 실패해 보수적 리포트로 대체했습니다.",
                    "현재 응답은 UI 렌더링과 워크플로우 검증용이며, 투자 판단에는 최신 공시 확인이 필요합니다.",
                    f"사용자 관심사항: {concerns}",
                ],
            ),
            sections=[
                ResearchSection(
                    id="business_model",
                    title="Business Model Breakdown",
                    summary="최신 사업부별 수치가 부족해 정성 요약만 제공합니다.",
                    bullets=["회사 공시, 투자자 발표자료, 최근 실적발표 자료 연결 시 자동 보강 가능합니다."],
                ),
                ResearchSection(
                    id="revenue_streams",
                    title="Revenue Streams",
                    summary="세그먼트별 매출 비중과 성장률은 확인이 필요합니다.",
                    tables=[
                        ResearchTable(
                            title="Revenue Streams",
                            columns=["Segment", "Revenue Contribution", "Growth", "Trajectory"],
                            rows=[["N/A", "N/A", "N/A", "N/A"]],
                        )
                    ],
                ),
                ResearchSection(
                    id="valuation_snapshot",
                    title="Valuation Snapshot",
                    summary="P/E, EV/Sales, EV/EBITDA, FCF yield의 최신 peer 비교가 필요합니다.",
                    tables=[
                        ResearchTable(
                            title="Valuation",
                            columns=["Metric", "Value"],
                            rows=[
                                ["Current Price", current_price or "N/A"],
                                ["Market Cap", market_cap or "N/A"],
                            ],
                        )
                    ],
                ),
            ],
            key_catalysts=["다음 실적 발표", "가이던스 변경", "제품/계약 뉴스"],
            key_risks=["데이터 부족", "밸류에이션 리스크", "실적 추정치 하향 리스크"],
            scenarios=[
                ResearchScenario(case="bull", thesis="성장률과 마진이 예상보다 견조한 경우.", assumptions=["컨센서스 상회"], price_target="N/A", probability="N/A"),
                ResearchScenario(case="base", thesis="현재 정보 기준 중립 시나리오.", assumptions=["추가 검증 필요"], price_target="N/A", probability="N/A"),
                ResearchScenario(case="bear", thesis="성장 둔화와 multiple compression이 동시에 발생하는 경우.", assumptions=["추정치 하향"], price_target="N/A", probability="N/A"),
            ],
            final_verdict="데이터 품질 제한으로 현재 판단은 Hold / Low Conviction입니다. 최신 공시와 컨센서스 확인 전 강한 매수/매도 의견은 부적절합니다.",
            analyst_assumptions=["정확한 최신 재무 데이터가 없을 때는 보수적 판단을 우선합니다."],
            data_gaps=gaps,
        )

    def _structured_to_markdown(self, report: StructuredEquityReport) -> str:
        box = report.rating_box
        lines = [
            f"# {box.ticker} Equity Research Report",
            "",
            "## 1. Summary Rating Box",
            "",
            "| 항목 | 내용 |",
            "|---|---|",
            f"| 티커 | {box.ticker} |",
            f"| 회사명 | {box.company_name or 'N/A'} |",
            f"| 현재가 | {box.current_price or 'N/A'} |",
            f"| 시가총액 | {box.market_cap or 'N/A'} |",
            f"| 투자의견 | {box.rating} |",
            f"| 확신도 | {box.conviction} |",
            f"| Base Case Target | {box.base_case_price_target or 'N/A'} |",
            f"| Bull Case Target | {box.bull_case_price_target or 'N/A'} |",
            f"| Bear Case Target | {box.bear_case_price_target or 'N/A'} |",
            f"| Expected Upside/Downside | {box.expected_upside_downside or 'N/A'} |",
            "",
            "### Key Thesis",
            "",
        ]
        lines.extend([f"- {item}" for item in box.key_thesis] or ["- N/A"])
        lines.append("")

        for index, section in enumerate(report.sections, start=2):
            lines.extend([f"## {index}. {section.title}", ""])
            if section.summary:
                lines.extend([section.summary, ""])
            lines.extend([f"- {item}" for item in section.bullets])
            if section.bullets:
                lines.append("")
            for table in section.tables:
                if table.title:
                    lines.extend([f"### {table.title}", ""])
                lines.extend(self._table_to_markdown(table))
                lines.append("")

        if report.key_catalysts:
            lines.extend(["## Key Catalysts", ""])
            lines.extend([f"- {item}" for item in report.key_catalysts])
            lines.append("")
        if report.key_risks:
            lines.extend(["## Key Risks", ""])
            lines.extend([f"- {item}" for item in report.key_risks])
            lines.append("")
        if report.scenarios:
            lines.extend(["## Scenarios", ""])
            for scenario in report.scenarios:
                lines.extend(
                    [
                        f"### {scenario.case.title()} Case",
                        "",
                        scenario.thesis,
                        "",
                        f"- Price target: {scenario.price_target or 'N/A'}",
                        f"- Probability: {scenario.probability or 'N/A'}",
                    ]
                )
                lines.extend([f"- Assumption: {item}" for item in scenario.assumptions])
                lines.append("")
        if report.analyst_assumptions:
            lines.extend(["## Analyst Assumptions", ""])
            lines.extend([f"- {item}" for item in report.analyst_assumptions])
            lines.append("")
        if report.data_gaps:
            lines.extend(["## Data Gaps", ""])
            lines.extend([f"- {item}" for item in report.data_gaps])
            lines.append("")
        lines.extend(["## Final Verdict", "", report.final_verdict or "N/A", ""])
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _table_to_markdown(table: ResearchTable) -> list[str]:
        if not table.columns:
            return []
        header = "| " + " | ".join(table.columns) + " |"
        sep = "| " + " | ".join("---" for _ in table.columns) + " |"
        rows = []
        for row in table.rows:
            padded = [str(cell) for cell in row[: len(table.columns)]]
            padded.extend([""] * (len(table.columns) - len(padded)))
            rows.append("| " + " | ".join(padded) + " |")
        return [header, sep, *rows]

    @staticmethod
    def _sources_for(ticker: str, market_snapshot: dict[str, Any]) -> list[EquityReportSource]:
        sources = [
            EquityReportSource(name="yfinance", url=f"https://finance.yahoo.com/quote/{ticker}", source_type="market_data"),
            EquityReportSource(name="SEC EDGAR", url=f"https://www.sec.gov/edgar/search/#/q={ticker}", source_type="filings"),
        ]
        if market_snapshot.get("website"):
            sources.append(EquityReportSource(name="Company website", url=str(market_snapshot["website"]), source_type="company"))
        return sources

    @staticmethod
    def _string_value(payload: dict[str, Any], key: str) -> str | None:
        value = payload.get(key)
        if value is None or value == "":
            return None
        return str(value)

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _load_yfinance_snapshot(self, ticker: str) -> dict[str, Any]:
        try:
            import yfinance as yf
        except Exception as exc:  # pragma: no cover
            return {"lookup_warning": f"yfinance_unavailable: {exc}"}

        ticker_obj = yf.Ticker(ticker)
        info: dict[str, Any] = {}
        try:
            info = dict(ticker_obj.get_info() or {})
        except Exception:
            try:
                info = dict(getattr(ticker_obj, "info", {}) or {})
            except Exception:
                info = {}

        fast_info: Any = {}
        try:
            fast_info = ticker_obj.fast_info
        except Exception:
            fast_info = {}

        def fast_get(name: str) -> Any:
            try:
                if isinstance(fast_info, dict):
                    return fast_info.get(name)
                return getattr(fast_info, name)
            except Exception:
                return None

        snapshot = {
            "company_name": info.get("longName") or info.get("shortName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "website": info.get("website"),
            "current_price": self._safe_float(fast_get("last_price") or info.get("currentPrice") or info.get("regularMarketPrice")),
            "market_cap": self._safe_float(fast_get("market_cap") or info.get("marketCap")),
            "currency": info.get("currency") or fast_get("currency"),
            "trailing_pe": self._safe_float(info.get("trailingPE")),
            "forward_pe": self._safe_float(info.get("forwardPE")),
            "price_to_sales": self._safe_float(info.get("priceToSalesTrailing12Months")),
            "enterprise_to_revenue": self._safe_float(info.get("enterpriseToRevenue")),
            "enterprise_to_ebitda": self._safe_float(info.get("enterpriseToEbitda")),
            "profit_margins": self._safe_float(info.get("profitMargins")),
            "gross_margins": self._safe_float(info.get("grossMargins")),
            "operating_margins": self._safe_float(info.get("operatingMargins")),
            "revenue_growth": self._safe_float(info.get("revenueGrowth")),
            "earnings_growth": self._safe_float(info.get("earningsGrowth")),
            "total_cash": self._safe_float(info.get("totalCash")),
            "total_debt": self._safe_float(info.get("totalDebt")),
            "free_cashflow": self._safe_float(info.get("freeCashflow")),
            "operating_cashflow": self._safe_float(info.get("operatingCashflow")),
            "recommendation_key": info.get("recommendationKey"),
            "target_mean_price": self._safe_float(info.get("targetMeanPrice")),
            "beta": self._safe_float(info.get("beta")),
        }
        return {key: value for key, value in snapshot.items() if value is not None and value != ""}


__all__ = ["EquityResearchReportService", "MarketDataProvider"]
