# Dartmouth backend

This FastAPI service creates and stores proposals in SQLite, returns two fixed questions for each proposal, and uses a temporary grader: an answer passes when it contains more than 20 non-whitespace characters. `GET /check` always returns `{ "pass": true }` during this fake-data stage.

Every endpoint requires `X-Gate-Secret` to match `GATE_SECRET` in the repository-root `.env` file. The existing `.env` stays untracked. See `.env.example` for the supported settings.

## Run locally

From this `backend` directory:

```powershell
python -m uv sync --all-groups
python -m uv run uvicorn main:app --reload
```

The default database is `backend/dartmouth.db`. Override it by setting `DATABASE_URL` in the repository-root `.env` file. Open http://127.0.0.1:8000/docs and use `X-Gate-Secret` as the API-key header value.

To run the checks:

```powershell
python -m uv run pytest
```

For a Railway deployment with PostgreSQL, see [DEPLOY.md](DEPLOY.md).
