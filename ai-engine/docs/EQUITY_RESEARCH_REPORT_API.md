# Equity Research Report API

This API is the production-oriented frontend contract for ticker-level equity
research reports. The primary response is structured JSON. `report_markdown` is
kept as a compatibility field for quick rendering, export, or copy/share flows.

## Flow

```text
Frontend /research
-> Backend POST /api/v1/research/equity-report
-> AI Engine POST /api/v1/research/equity-report
-> yfinance snapshot + Gemini structured JSON prompt
-> Pydantic validation
-> structured_report + derived report_markdown
-> Frontend renders cards/tables/sections from structured_report
```

The frontend should still call the Spring/Backend layer first in production. Do
not expose Gemini API keys from the browser.

## Endpoints

- `POST /v1/research/equity-report`
- `POST /api/v1/research/equity-report`

Both endpoints have the same request and response shape. The `/api/v1/*` alias is
intended for the original GitHub stack's Backend proxy convention.

## Request

```json
{
  "ticker": "NVDA",
  "concerns": "valuation, AI growth sustainability, margin risk",
  "language": "ko",
  "output_format": "structured"
}
```

Fields:

- `ticker`: required stock ticker.
- `concerns`: optional analyst concerns or user questions.
- `language`: `ko` or `en`, default `ko`.
- `output_format`: `structured` by default. `markdown` is accepted for compatibility but the response still includes `structured_report`.

## Response Shape

```json
{
  "ticker": "NVDA",
  "company_name": "NVIDIA Corporation",
  "generated_at": "2026-05-17T12:16:35Z",
  "language": "ko",
  "output_format": "structured",
  "structured_report": {
    "rating_box": {
      "ticker": "NVDA",
      "company_name": "NVIDIA Corporation",
      "current_price": "$123.45",
      "market_cap": "$1.0B",
      "rating": "Hold",
      "conviction": "Medium",
      "base_case_price_target": "$130",
      "bull_case_price_target": "$160",
      "bear_case_price_target": "$90",
      "expected_upside_downside": "+5.3%",
      "key_thesis": ["AI demand remains strong"]
    },
    "sections": [
      {
        "id": "valuation_snapshot",
        "title": "Valuation Snapshot",
        "summary": "The stock trades at a premium multiple.",
        "bullets": [],
        "tables": [
          {
            "title": "Valuation",
            "columns": ["Metric", "Value"],
            "rows": [["Trailing P/E", "35.5"]]
          }
        ]
      }
    ],
    "key_catalysts": ["Next earnings report"],
    "key_risks": ["Valuation compression"],
    "scenarios": [
      {
        "case": "base",
        "thesis": "Growth normalizes.",
        "assumptions": ["Consensus met"],
        "price_target": "$130",
        "probability": "50%"
      }
    ],
    "final_verdict": "Hold with medium conviction.",
    "analyst_assumptions": ["Numbers should be verified against filings."],
    "data_gaps": []
  },
  "report_markdown": "# NVDA Equity Research Report\n...",
  "sources": [
    {
      "name": "yfinance",
      "url": "https://finance.yahoo.com/quote/NVDA",
      "source_type": "market_data"
    }
  ],
  "data_quality": {
    "freshness": "live_or_recent",
    "missing_items": [],
    "warnings": []
  },
  "market_snapshot": {
    "current_price": 123.45,
    "market_cap": 1000000000
  },
  "model": "gemini-3.1-pro-preview",
  "model_route": "review",
  "prompt_tokens": 123,
  "output_tokens": 456,
  "estimated_cost_usd": 0.0123,
  "fallback_used": false
}
```

## Frontend Rendering Contract

Recommended frontend layout:

- Search/input card: ticker, concerns, generate button.
- Hero/rating card: `structured_report.rating_box`.
- Section navigation: `structured_report.sections[].id/title`.
- Body cards: `structured_report.sections[]`.
- Tables: `sections[].tables[]` with `columns` and `rows`.
- Catalyst/risk chips: `key_catalysts` and `key_risks`.
- Scenario cards: `scenarios`.
- Source panel: `sources`.
- Warning panel: `data_quality.warnings` and `missing_items`.

If `fallback_used=true`, display a visible badge such as `데이터 제한 리포트`.
The report is still usable for UI testing, but should not be presented as a
fully verified investment note.

## Why Structured JSON Is The Source Of Truth

- Frontend cards do not depend on fragile Markdown parsing.
- Tables can be rendered with real table components.
- Badges, chips, section navigation, and mobile layout are deterministic.
- Schema failures are caught in the AI Engine and replaced by a conservative fallback.
- `report_markdown` can still support export, copy, or simple preview mode.

## Failure Behavior

The API is designed to degrade gracefully:

- yfinance failure: report generation continues with missing market-data warning.
- Gemini failure: a conservative structured fallback report is returned.
- Gemini schema failure: invalid output is rejected and fallback is returned.
- Invalid ticker: request validation returns HTTP 422.

Existing analyze, Redis, control, calibration, regression, and stats contracts
are unchanged.
