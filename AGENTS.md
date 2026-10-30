# Instructions for Codex

We are building the Comprehension Gate. You are working on the backend
that generates and grades comprehension questions, and the GitHub Action
that checks pull requests.

- Read CONTRACT.md before writing any endpoint. Match it exactly.
- Never edit CONTRACT.md. If it needs to change, stop and tell me why.
- Only create or edit files in backend/ and action/ unless I say otherwise.
- Python 3.11+, uv for dependencies, FastAPI for the backend.
- Use SQLAlchemy with a DATABASE_URL environment variable:
  SQLite locally, Postgres when deployed.
- Use the official anthropic Python SDK. Model name comes from the MODEL env var.
- Read secrets from environment variables or a .env file. Never hardcode them.
- I am new to this. After each task, explain in plain language what you
  built and give me the exact commands to test it.
- Write tests for anything with logic in it.