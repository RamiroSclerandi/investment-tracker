# Investment Tracker

Personal portfolio tracker for crypto and Argentine market assets, with live valuation and P&L in ARS or USD (MEP).

## Layout

- `apps/api` — FastAPI backend (Python 3.14, uv)
- `apps/web` — React SPA (Vite, TypeScript, pnpm)

## Requirements

- Python 3.14.4 and [uv](https://docs.astral.sh/uv/)
- Node 24 and pnpm 12

## API

```bash
cd apps/api
uv sync
uv run pytest -q
uv run ruff check . && uv run ruff format --check . && uv run mypy .
DATABASE_URL=... uv run uvicorn investment_tracker.main:build_app --factory --reload
```

## Tests

Unit tests, lint and type checks run on the host (`uv run pytest -q -m "not integration"`).
Integration tests need PostgreSQL and run inside the compose network, because published ports do not reach Windows:

```bash
podman compose --profile test run --rm api-test
```

In CI, integration tests start PostgreSQL with testcontainers when `DATABASE_URL` is unset.

## Web

```bash
cd apps/web
pnpm install
pnpm dev
pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

`pnpm dev` proxies `/api` to `http://localhost:8000`. The API client is generated from the backend OpenAPI schema: run `pnpm api:generate` after changing an endpoint and commit `src/api/openapi.json` and `src/api/generated/schema.ts`; `pnpm api:check` fails when they are stale.

Copy `.env.example` to `.env` and adjust the values for local development.

## Containers

```bash
podman compose up -d --build
```

Starts `postgres`, `mailpit`, `api` (port 8000) and `web` (nginx on port 8080, proxying `/api/` to the `api` service; override with `API_UPSTREAM`). Published ports do not reach Windows on this Podman setup, so check the services from inside the network, e.g. `podman exec investment-tracker-web-1 wget -qO- http://127.0.0.1:8080/api/v1/healthz`.

## CI

`.github/workflows/ci.yml` runs on pull requests: Conventional Commits title lint, api (ruff, format check, mypy, unit and testcontainers integration tests), web (eslint, tsc, vitest, build, generated-client freshness) and gitleaks.
