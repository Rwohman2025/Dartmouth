# Deploy to Railway

This guide deploys the FastAPI backend and a managed PostgreSQL database from GitHub. The included `Dockerfile` runs this command in production:

```sh
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Railway provides `PORT`; the `8000` fallback only helps when running the container locally. The app accepts `DATABASE_URL` values beginning with either `postgres://` or `postgresql://`.

## 1. Push the backend changes to GitHub

Commit and push the `backend/` files, including `pyproject.toml`, `uv.lock`, and `Dockerfile`. Do not commit `.env`, local SQLite databases, or `.venv`.

## 2. Create the Railway project and connect GitHub

1. Go to [Railway](https://railway.app/) and sign in with GitHub.
2. Choose **New Project** and then **Deploy from GitHub repo**.
3. Select the Dartmouth repository and let Railway create the service.

## 3. Point the service at `backend`

1. Select the new service in the Railway project canvas.
2. Open **Settings** → **Build**.
3. Set **Root Directory** to `/backend` and save.
4. Railway should detect `backend/Dockerfile`. If it does not, set **Dockerfile Path** to `/backend/Dockerfile`.
5. Leave the service start command empty: the Dockerfile supplies the Uvicorn start command.

## 4. Add PostgreSQL

1. On the project canvas, click **+ New** → **Database** → **PostgreSQL**.
2. Wait for the Postgres service to become ready.
3. Select the backend service, open **Variables**, and add `DATABASE_URL` as a **reference variable** to the Postgres service's `DATABASE_URL`. Do not copy a password into source code.

## 5. Add backend environment variables

In the backend service's **Variables** tab, add these values:

| Variable | Value |
| --- | --- |
| `ANTHROPIC_API_KEY` | Your Anthropic API key. It is reserved for the later real-grading implementation. |
| `GATE_SECRET` | A new long random secret used by the `X-Gate-Secret` request header. |
| `MODEL` | The model identifier you intend to use later. |
| `DATABASE_URL` | The Postgres reference from step 4. |

Save the variables and deploy. The application creates its three tables (`proposals`, `questions`, and `attempts`) when it starts.

## 6. Deploy and verify

1. Open the deployment logs. A successful deployment shows Uvicorn listening on `0.0.0.0` with Railway's port.
2. In **Settings** → **Networking**, choose **Generate Domain**.
3. Open `https://YOUR-DOMAIN/docs` to view the API.
4. Verify the deployment from a terminal. Replace the placeholders; do not paste your actual secret into a public shell history or screenshot.

```sh
curl https://YOUR-DOMAIN/health -H "X-Gate-Secret: YOUR_GATE_SECRET"
```

The existing `/health` endpoint requires the gate secret. Do not configure Railway's unauthenticated HTTP health check for that path unless you first add a separate public readiness endpoint.

## Future deployments

Every push to the connected GitHub branch triggers a new Railway deployment. The Postgres database persists separately from application deployments.
