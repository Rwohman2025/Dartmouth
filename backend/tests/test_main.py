import os
import tempfile
from pathlib import Path

os.environ["GATE_SECRET"] = "test-secret"
_database_file = Path(tempfile.gettempdir()) / "dartmouth-test.db"
if _database_file.exists():
    _database_file.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{_database_file.as_posix()}"

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402


def test_normalizes_postgres_url_schemes():
    assert main.normalize_database_url("postgres://user:password@db:5432/dartmouth") == (
        "postgresql+psycopg://user:password@db:5432/dartmouth"
    )
    assert main.normalize_database_url("postgresql://user:password@db:5432/dartmouth") == (
        "postgresql+psycopg://user:password@db:5432/dartmouth"
    )


def test_line_numbering_and_invalid_json_retry(monkeypatch):
    assert main.add_line_numbers("first\nsecond") == "0001 | first\n0002 | second"
    responses = iter(["not json", '{"passed": true, "feedback": "Correct."}'])
    content_seen: list[str] = []

    def fake_call(_system, content):
        content_seen.append(content)
        return next(responses)

    monkeypatch.setattr(main, "_call_anthropic", fake_call)
    result = main.request_json("grade.txt", "test", main.GradedAnswer)
    assert result.passed is True
    assert result.feedback == "Correct."
    assert "output_repair" in content_seen[1]


def test_grade_response_maps_hint_to_feedback(monkeypatch):
    monkeypatch.setattr(
        main,
        "request_json",
        lambda *_args: main.ModelGradeResponse(passed=False, hint="Check the comparison.", hint_line=15),
    )
    result = main.grade_answer("x", main.GeneratedQuestion(prompt="Why?", rubric="Explain."), "No idea")
    assert result == main.GradedAnswer(passed=False, feedback="Check the comparison. See line 0015.")


def test_proposal_lifecycle_uses_model_results_and_hides_rubrics(monkeypatch):
    generated = [
        main.GeneratedQuestion(prompt="What happens at line 0001?", rubric="Require the exact boundary explanation."),
    ]
    monkeypatch.setattr(main, "generate_questions", lambda code: generated)
    monkeypatch.setattr(
        main,
        "grade_answer",
        lambda _code, _question, answer: main.GradedAnswer(
            passed=answer == "correct answer", feedback="Model evaluation completed."
        ),
    )

    headers = {"X-Gate-Secret": "test-secret"}
    with TestClient(main.app) as client:
        assert client.get("/health", headers=headers).json()["implementation"] == "anthropic"
        created = client.post(
            "/v1/proposals",
            headers=headers,
            json={
                "repository": "Rwohman2025/Dartmouth",
                "commit_sha": "a" * 40,
                "diff": "first\nsecond",
                "summary": "Example change",
            },
        )
        assert created.status_code == 201
        proposal_id = created.json()["proposal_id"]
        questions = client.get(f"/v1/proposals/{proposal_id}/questions", headers=headers).json()["questions"]
        assert len(questions) == 1
        assert all("rubric" not in question for question in questions)
        proposal_response = client.get(f"/v1/proposals/{proposal_id}", headers=headers)
        assert "rubric" not in proposal_response.text

        grade = client.post(
            f"/v1/proposals/{proposal_id}/grade",
            headers=headers,
            json={"answers": [{"question_id": question["question_id"], "answer": "correct answer"} for question in questions]},
        )
        assert grade.status_code == 200
        assert grade.json()["status"] == "approved"
        assert client.get("/check", headers=headers).json() == {"pass": True}
