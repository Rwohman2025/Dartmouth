import os
import tempfile
from pathlib import Path

os.environ["GATE_SECRET"] = "test-secret"
_database_file = Path(tempfile.gettempdir()) / "dartmouth-test.db"
if _database_file.exists():
    _database_file.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{_database_file.as_posix()}"

from fastapi.testclient import TestClient  # noqa: E402
from main import app, normalize_database_url  # noqa: E402


def test_normalizes_postgres_url_schemes():
    assert normalize_database_url("postgres://user:password@db:5432/dartmouth") == (
        "postgresql+psycopg://user:password@db:5432/dartmouth"
    )
    assert normalize_database_url("postgresql://user:password@db:5432/dartmouth") == (
        "postgresql+psycopg://user:password@db:5432/dartmouth"
    )


def test_proposal_lifecycle_and_fake_check():
    headers = {"X-Gate-Secret": "test-secret"}
    with TestClient(app) as client:
        assert client.get("/health", headers=headers).status_code == 200
        assert client.get("/health", headers={"X-Gate-Secret": "wrong"}).status_code == 401
        created = client.post(
            "/v1/proposals",
            headers=headers,
            json={
                "repository": "Rwohman2025/Dartmouth",
                "commit_sha": "a" * 40,
                "diff": "diff --git a/a b/a",
                "summary": "Example change",
            },
        )
        assert created.status_code == 201
        proposal_id = created.json()["proposal_id"]
        questions = client.get(f"/v1/proposals/{proposal_id}/questions", headers=headers).json()["questions"]
        assert len(questions) == 2
        grade = client.post(
            f"/v1/proposals/{proposal_id}/grade",
            headers=headers,
            json={
                "answers": [
                    {"question_id": question["question_id"], "answer": "This answer is safely longer than twenty characters."}
                    for question in questions
                ]
            },
        )
        assert grade.status_code == 200
        assert grade.json()["status"] == "approved"
        assert client.get("/check", headers=headers).json() == {"pass": True}
