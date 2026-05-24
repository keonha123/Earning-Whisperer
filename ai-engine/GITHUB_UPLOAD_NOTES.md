# GitHub Upload Notes

## Package

This package is prepared as the GitHub-ready AI engine release for EarningWhisperer v9.5.9.

## Included

- FastAPI AI engine source
- Strategy orchestration and gate logic
- Productized signal envelope and Signal Brief
- Institutional Edge Pack
- Decision Assistant layer
- Original GitHub legacy compatibility adapter for `/api/v1/analyze`
- Redis raw-signal publishing for `trading-signals`
- Offline research/backtest tooling
- Backtest artifacts and validation docs
- Unit tests
- SQL schema
- Operational docs and changelog

## Excluded From Release Zip

- `__pycache__/`
- `.pytest_cache/`
- `.pytest_tmp/`
- `pytest_tmp/`
- `pytest-cache-files-*/`
- `*.pyc`
- local virtual environments
- local secret files such as `.env`

## Validation Commands

```powershell
py -3.13 -m compileall api core models services tools tests -q
py -3.13 -m pytest -q
py -3.13 -m pip check
```

## Latest Validation

- Compile validation: success
- Full tests: `135 passed`
- Dependency check: `No broken requirements found`

## Operational Boundary

This AI engine generates advisory signals and order-draft previews. It does not execute broker orders by itself.
