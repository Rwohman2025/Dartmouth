# Dartmouth backend

This FastAPI service stores proposals in SQLite or PostgreSQL, generates questions through Anthropic, and grades answers against a private rubric. Questions and answers are sent to Anthropic with one-based line numbers added to the submitted code. `POST /check` compares a pull-request unified diff with unpassed proposals and returns matching review URLs.

Every endpoint requires `X-Gate-Secret` to match `GATE_SECRET` in the repository-root `.env` file. The existing `.env` stays untracked. See `.env.example` for the supported settings.

Set `BACKEND_URL` as well as `ANTHROPIC_API_KEY` and `MODEL` in the repository-root `.env` file. `BACKEND_URL` is used to construct `/review/{proposal_id}` URLs returned by `POST /check`. Edit `prompts/generate.txt` and `prompts/grade.txt` to change the model instructions without changing Python code. Rubrics are stored in the database and are never returned by API routes.

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

Run the Anthropic evaluation over `demo/snippets` and `demo/ANSWER_KEY.md` with:

```powershell
python -m uv run python eval.py
```

For a Railway deployment with PostgreSQL, see [DEPLOY.md](DEPLOY.md).
