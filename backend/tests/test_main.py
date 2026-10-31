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
    result = main.request_json("grade.txt", "test", main.ModelGradeResponse)
    assert result.passed is True
    assert result.feedback == "Correct."
    assert "output_repair" in content_seen[1]


def test_request_json_accepts_a_single_markdown_json_fence(monkeypatch):
    monkeypatch.setattr(
        main,
        "_call_anthropic",
        lambda _system, _content: '```json\n{"passed": true, "hint": "", "hint_line": null}\n```',
    )
    result = main.request_json("grade.txt", "test", main.ModelGradeResponse)
    assert result.passed is True
    assert result.hint == ""


def test_model_http_errors_describe_api_and_json_failures():
    assert main.model_http_error(main.ModelRequestError()).detail == (
        "Anthropic could not process the request. Check ANTHROPIC_API_KEY, MODEL, and Railway's deployment logs."
    )
    assert main.model_http_error(main.ModelOutputError()).detail == (
        "The question-generation model did not return the expected JSON after one retry."
    )


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
    assert result == main.GradedAnswer(passed=False, hint="Check the comparison. See line 0015.", hint_line=15)


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
            passed=answer == "correct answer", hint="Model evaluation completed."
        ),
    )

    headers = {"X-Gate-Secret": "test-secret"}
    with TestClient(main.app) as client:
        assert client.get("/health", headers=headers).json()["implementation"] == "anthropic"
        created = client.post(
            "/proposals",
            headers=headers,
            json={
                "repo": "Rwohman2025/Dartmouth",
                "file_path": "src/example.py",
                "code": "first\nsecond",
                "task": "Example change",
            },
        )
        assert created.status_code == 201
        created_body = created.json()
        proposal_id = created_body["proposal_id"]
        questions = created_body["questions"]
        assert len(questions) == 1
        assert all("rubric" not in question for question in questions)
        proposal_response = client.get(f"/proposals/{proposal_id}", headers=headers)
        assert "rubric" not in proposal_response.text

        grade = client.post(
            f"/proposals/{proposal_id}/answers",
            headers=headers,
            json={"answers": [{"question_id": question["id"], "answer": "correct answer"} for question in questions]},
        )
        assert grade.status_code == 200
        assert grade.json()["passed"] is True
        proposal_after_grade = client.get(f"/proposals/{proposal_id}", headers=headers).json()
        assert proposal_after_grade == {
            "proposal_id": proposal_id,
            "repo": "Rwohman2025/Dartmouth",
            "file_path": "src/example.py",
            "status": "passed",
            "attempts": 1,
        }
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


def add_question(proposal: main.Proposal) -> main.Question:
    question = main.Question(
        id=str(uuid4()), proposal_id=proposal.id,
        prompt="What happens when this function receives an empty list?",
        rubric="The answer must describe the division by zero.",
        line_start=1,
        line_end=2,
    )
    with main.SessionLocal() as session:
        session.add(question)
        session.commit()
    return question


def test_public_review_page_hides_rubric_and_displays_passed_result(monkeypatch):
    monkeypatch.setattr(
        main,
        "grade_answer",
        lambda _code, _question, _answer: main.GradedAnswer(passed=True, hint="Answer passed review."),
    )
    with TestClient(main.app) as client:
        proposal = seed_proposal("team/review", "src/example.py", "def average(values):\n    return sum(values) / len(values)")
        question = add_question(proposal)
        page = client.get(f"/review/{proposal.id}")
        assert page.status_code == 200
        assert "src/example.py" in page.text
        assert "0001" in page.text
        assert question.prompt in page.text
        assert question.rubric not in page.text

        submitted = client.post(f"/review/{proposal.id}/answers", data={f"answer_{question.id}": "It divides by zero."})
    assert submitted.status_code == 200
    assert "Passed" in submitted.text


def test_public_review_page_displays_grading_hint(monkeypatch):
    monkeypatch.setattr(
        main,
        "grade_answer",
        lambda _code, _question, _answer: main.GradedAnswer(passed=False, hint="Check the division on line 0002."),
    )
    with TestClient(main.app) as client:
        proposal = seed_proposal("team/review-hint", "src/example.py", "def average(values):\n    return sum(values) / len(values)")
        question = add_question(proposal)
        submitted = client.post(f"/review/{proposal.id}/answers", data={f"answer_{question.id}": "It is fine."})
    assert submitted.status_code == 200
    assert "Review needs another answer" in submitted.text
    assert "Check the division on line 0002." in submitted.text
