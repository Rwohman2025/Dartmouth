import os
import tempfile
from pathlib import Path
from uuid import uuid4

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


def test_generated_question_uses_the_prompt_file_schema():
    result = main.GeneratedQuestions.model_validate_json(
        '{"questions":[{"id":"q1","line_start":2,"line_end":3,"question":"What happens?","rubric":"Explain behavior."}]}'
    )
    assert result.questions[0].prompt == "What happens?"


def test_grade_response_maps_hint_to_feedback(monkeypatch):
    monkeypatch.setattr(
        main,
        "request_json",
        lambda *_args: main.ModelGradeResponse(passed=False, hint="Check the comparison.", hint_line=15),
    )
    result = main.grade_answer(
        "x", main.GeneratedQuestion(id="q1", line_start=1, line_end=1, question="Why?", rubric="Explain."), "No idea"
    )
    assert result == main.GradedAnswer(passed=False, feedback="Check the comparison. See line 0015.")


def test_proposal_lifecycle_uses_model_results_and_hides_rubrics(monkeypatch):
    generated = [
        main.GeneratedQuestion(
            id="q1", line_start=1, line_end=1,
            question="What happens at line 0001?", rubric="Require the exact boundary explanation."
        ),
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
        assert client.post("/check", headers=headers, json={"repo": "other/repo", "diff": "diff --git a/a b/a"}).json() == {
            "status": "pass", "unanswered": []
        }


def unified_diff(file_path: str, lines: list[str]) -> str:
    return "\n".join(
        [
            f"diff --git a/{file_path} b/{file_path}",
            f"--- a/{file_path}",
            f"+++ b/{file_path}",
            *(f"+{line}" for line in lines),
        ]
    )


def seed_proposal(repo: str, file_path: str, code: str, proposal_status: str = "pending") -> main.Proposal:
    proposal = main.Proposal(
        id=str(uuid4()),
        repository=repo,
        file_path=file_path,
        commit_sha="b" * 40,
        diff=code,
        summary="Matching test proposal",
        status=proposal_status,
        created_at=main.utc_now(),
    )
    with main.SessionLocal() as session:
        session.add(proposal)
        session.commit()
    return proposal


def post_check(client: TestClient, repo: str, diff: str) -> dict:
    return client.post("/check", headers={"X-Gate-Secret": "test-secret"}, json={"repo": repo, "diff": diff}).json()


def test_check_flags_an_exact_paste():
    with TestClient(main.app) as client:
        proposal = seed_proposal("team/exact", "src/example.py", "def greet():\n    return 'hello'\nprint(greet())")
        result = post_check(client, "team/exact", unified_diff("src/example.py", proposal.diff.splitlines()))
    assert result == {
        "status": "fail",
        "unanswered": [{
            "proposal_id": proposal.id,
            "file_path": "src/example.py",
            "review_url": f"http://localhost:8000/review/{proposal.id}",
        }],
    }


def test_check_flags_a_paste_with_changed_indentation():
    with TestClient(main.app) as client:
        proposal = seed_proposal("team/indent", "src/example.py", "def greet():\n    return 'hello'\nprint(greet())")
        diff = unified_diff("src/example.py", ["def greet():", "  return 'hello'", "print(greet())"])
        result = post_check(client, "team/indent", diff)
    assert result["status"] == "fail"
    assert result["unanswered"][0]["proposal_id"] == proposal.id


def test_check_ignores_unrelated_code():
    with TestClient(main.app) as client:
        seed_proposal("team/unrelated", "src/example.py", "alpha = 1\nbeta = 2\ngamma = 3")
        result = post_check(client, "team/unrelated", unified_diff("src/example.py", ["delta = 4", "epsilon = 5"]))
    assert result == {"status": "pass", "unanswered": []}


def test_check_ignores_a_proposal_that_already_passed():
    with TestClient(main.app) as client:
        proposal = seed_proposal("team/passed", "src/example.py", "x = 1\ny = 2", proposal_status="passed")
        result = post_check(client, "team/passed", unified_diff("src/example.py", proposal.diff.splitlines()))
    assert result == {"status": "pass", "unanswered": []}
