"""Dartmouth's FastAPI gate backed by Anthropic question generation and grading."""

from __future__ import annotations

import hmac
import json
import os
from html import escape
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Literal, TypeVar
from urllib.parse import parse_qs
from uuid import uuid4

from anthropic import APIError, Anthropic
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.responses import HTMLResponse
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, create_engine, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIRECTORY = Path(__file__).resolve().parent / "prompts"
load_dotenv(REPOSITORY_ROOT / ".env")


def normalize_database_url(database_url: str) -> str:
    """Make Railway/Render's postgres:// URLs explicit for SQLAlchemy + psycopg."""
    if database_url.startswith("postgres://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgres://")
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
    return database_url


DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL", "sqlite:///./dartmouth.db"))
engine_options: dict[str, object] = {}
if DATABASE_URL.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}
engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    repository: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True, index=True)
    commit_sha: Mapped[str] = mapped_column(String(128))
    diff: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    questions: Mapped[list["Question"]] = relationship(back_populates="proposal", cascade="all, delete-orphan")
    attempts: Mapped[list["Attempt"]] = relationship(back_populates="proposal", cascade="all, delete-orphan")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), index=True)
    prompt: Mapped[str] = mapped_column(Text)
    rubric: Mapped[str] = mapped_column(Text)
    line_start: Mapped[int | None] = mapped_column(nullable=True)
    line_end: Mapped[int | None] = mapped_column(nullable=True)
    proposal: Mapped[Proposal] = relationship(back_populates="questions")
    attempts: Mapped[list["Attempt"]] = relationship(back_populates="question")


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), index=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"), index=True)
    answer: Mapped[str] = mapped_column(Text)
    passed: Mapped[bool] = mapped_column(Boolean)
    feedback: Mapped[str] = mapped_column(Text)
    hint_line: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    proposal: Mapped[Proposal] = relationship(back_populates="attempts")
    question: Mapped[Question] = relationship(back_populates="attempts")


class ProposalInput(BaseModel):
    repo: str = Field(min_length=1)
    file_path: str = Field(min_length=1)
    code: str = Field(min_length=1)
    task: str = Field(min_length=1)


class AnswerInput(BaseModel):
    question_id: str = Field(min_length=1)
    answer: str = Field(min_length=1)


class GradeInput(BaseModel):
    answers: list[AnswerInput] = Field(min_length=1)


class QuestionResponse(BaseModel):
    id: str
    line_start: int
    line_end: int
    question: str


class ProposalCreateResponse(BaseModel):
    proposal_id: str
    questions: list[QuestionResponse]


class AnswerResult(BaseModel):
    question_id: str
    passed: bool
    hint: str
    hint_line: int | None


class AnswerResponse(BaseModel):
    passed: bool
    results: list[AnswerResult]


class ProposalResponse(BaseModel):
    proposal_id: str
    repo: str
    file_path: str
    status: Literal["pending", "passed"]
    attempts: int


class CheckInput(BaseModel):
    repo: str = Field(min_length=1)
    diff: str = Field(min_length=1)


class UnansweredProposal(BaseModel):
    proposal_id: str
    file_path: str
    review_url: str


class CheckResponse(BaseModel):
    status: Literal["pass", "fail"]
    unanswered: list[UnansweredProposal]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GeneratedQuestion(StrictModel):
    id: str = Field(min_length=1)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    question: str = Field(min_length=1)
    rubric: str = Field(min_length=1)

    @property
    def prompt(self) -> str:
        """Compatibility name for storage and grading code."""
        return self.question


class GeneratedQuestions(StrictModel):
    questions: list[GeneratedQuestion] = Field(min_length=1, max_length=1)


class GradingQuestion(StrictModel):
    prompt: str = Field(min_length=1)
    rubric: str = Field(min_length=1)


class ModelGradeResponse(StrictModel):
    passed: bool
    feedback: str | None = None
    hint: str | None = None
    hint_line: int | None = Field(default=None, ge=1)


class GradedAnswer(StrictModel):
    passed: bool
    hint: str = Field(min_length=1)
    hint_line: int | None = Field(default=None, ge=1)


class ModelConfigurationError(RuntimeError):
    pass


class ModelOutputError(RuntimeError):
    pass


class ModelRequestError(RuntimeError):
    pass


ParsedModel = TypeVar("ParsedModel", bound=BaseModel)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def add_line_numbers(code: str) -> str:
    """Return the exact submitted code with stable, one-based line labels."""
    return "\n".join(f"{line_number:04d} | {line}" for line_number, line in enumerate(code.splitlines(), start=1))


def normalize_source_line(line: str) -> str:
    """Ignore all whitespace so indentation-only changes still match."""
    return "".join(line.split())


def parse_added_lines(unified_diff: str) -> dict[str, set[str]]:
    """Collect non-blank added lines by their repository-relative file path."""
    added_by_file: dict[str, set[str]] = {}
    current_path: str | None = None
    for line in unified_diff.splitlines():
        if line.startswith("+++ "):
            candidate = line[4:].strip()
            if candidate == "/dev/null":
                current_path = None
            elif candidate.startswith("b/"):
                current_path = candidate[2:]
                added_by_file.setdefault(current_path, set())
            else:
                current_path = candidate
                added_by_file.setdefault(current_path, set())
            continue
        if current_path is None or not line.startswith("+") or line.startswith("+++"):
            continue
        normalized = normalize_source_line(line[1:])
        if normalized:
            added_by_file[current_path].add(normalized)
    return added_by_file


def proposal_match_ratio(proposal_code: str, added_lines: set[str]) -> float:
    proposal_lines = [
        normalized for raw_line in proposal_code.splitlines()
        if (normalized := normalize_source_line(raw_line))
    ]
    if not proposal_lines:
        return 0.0
    matches = sum(line in added_lines for line in proposal_lines)
    return matches / len(proposal_lines)


def initialize_database() -> None:
    """Create fresh tables and add contract fields to pre-existing databases."""
    Base.metadata.create_all(bind=engine)
    proposal_columns = {column["name"] for column in inspect(engine).get_columns("proposals")}
    question_columns = {column["name"] for column in inspect(engine).get_columns("questions")}
    attempt_columns = {column["name"] for column in inspect(engine).get_columns("attempts")}
    with engine.begin() as connection:
        if "file_path" not in proposal_columns:
            connection.execute(text("ALTER TABLE proposals ADD COLUMN file_path VARCHAR(1024)"))
        if "line_start" not in question_columns:
            connection.execute(text("ALTER TABLE questions ADD COLUMN line_start INTEGER"))
        if "line_end" not in question_columns:
            connection.execute(text("ALTER TABLE questions ADD COLUMN line_end INTEGER"))
        if "hint_line" not in attempt_columns:
            connection.execute(text("ALTER TABLE attempts ADD COLUMN hint_line INTEGER"))


def load_prompt(name: str) -> str:
    try:
        return (PROMPTS_DIRECTORY / name).read_text(encoding="utf-8")
    except OSError as error:
        raise ModelConfigurationError(f"Prompt file {name} could not be read.") from error


def _call_anthropic(system_prompt: str, user_content: str) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    model = os.getenv("MODEL", "claude-sonnet-5-5")
    if not api_key:
        raise ModelConfigurationError("ANTHROPIC_API_KEY must be configured.")
    try:
        response = Anthropic(api_key=api_key).messages.create(
            model=model,
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
    except APIError as error:
        raise ModelRequestError("Anthropic did not complete the request.") from error
    text = "\n".join(block.text for block in response.content if hasattr(block, "text"))
    if not text:
        raise ModelOutputError("Anthropic returned no text output.")
    return text


def parse_model_json(raw_output: str, output_type: type[ParsedModel]) -> ParsedModel:
    """Validate a JSON response, allowing only a single outer Markdown fence."""
    candidate = raw_output.strip()
    if candidate.startswith("```"):
        fence_end = candidate.find("\n")
        if fence_end == -1 or not candidate.endswith("```"):
            raise ValueError("Model response has an incomplete Markdown fence.")
        candidate = candidate[fence_end + 1:-3].strip()
    return output_type.model_validate_json(candidate)


def request_json(prompt_name: str, user_content: str, output_type: type[ParsedModel]) -> ParsedModel:
    """Validate model JSON and make exactly one retry for malformed output."""
    system_prompt = load_prompt(prompt_name)
    retry_content = user_content
    for attempt in range(2):
        try:
            raw_output = _call_anthropic(system_prompt, retry_content)
        except ModelOutputError as error:
            if attempt == 1:
                raise ModelOutputError("Anthropic returned invalid JSON twice.") from error
            retry_content = f"{user_content}\n\n<output_repair>Return JSON only. It must exactly match this schema, including every required key and no extra keys: {json.dumps(output_type.model_json_schema(), separators=(',', ':'))}</output_repair>"
            continue
        try:
            return parse_model_json(raw_output, output_type)
        except (ValidationError, ValueError) as error:
            if attempt == 1:
                raise ModelOutputError("Anthropic returned invalid JSON twice.") from error
            retry_content = f"{user_content}\n\n<output_repair>Return JSON only. Your prior JSON was invalid. It must exactly match this schema, including every required key and no extra keys: {json.dumps(output_type.model_json_schema(), separators=(',', ':'))}</output_repair>"
    raise AssertionError("The JSON retry loop must return or raise.")


def generate_questions(code: str) -> list[GeneratedQuestion]:
    result = request_json(
        "generate.txt",
        f"<code_with_line_numbers>\n{add_line_numbers(code)}\n</code_with_line_numbers>",
        GeneratedQuestions,
    )
    return result.questions


def grade_answer(code: str, question: GeneratedQuestion | GradingQuestion, answer: str) -> GradedAnswer:
    result = request_json(
        "grade.txt",
        "\n".join(
            [
                f"<question>\n{question.prompt}\n</question>",
                f"<rubric>\n{question.rubric}\n</rubric>",
                f"<candidate_answer>\n{answer}\n</candidate_answer>",
                f"<code_with_line_numbers>\n{add_line_numbers(code)}\n</code_with_line_numbers>",
            ]
        ),
        ModelGradeResponse,
    )
    hint = result.feedback or result.hint
    if not hint:
        hint = "Answer passed review." if result.passed else "Answer did not satisfy the grading rubric."
    if result.hint_line is not None:
        hint = f"{hint} See line {result.hint_line:04d}."
    return GradedAnswer(passed=result.passed, hint=hint, hint_line=result.hint_line)


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def require_gate_secret(x_gate_secret: str | None = Header(default=None)) -> None:
    expected_secret = os.getenv("GATE_SECRET")
    if not expected_secret:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="GATE_SECRET is not configured.")
    if not x_gate_secret or not hmac.compare_digest(x_gate_secret, expected_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid X-Gate-Secret.")


def get_proposal_or_404(session: Session, proposal_id: str) -> Proposal:
    proposal = session.get(Proposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found.")
    return proposal


def question_payload(question: Question) -> QuestionResponse:
    """The client sees the question but never the stored rubric."""
    return QuestionResponse(
        id=question.id,
        line_start=question.line_start or 1,
        line_end=question.line_end or question.line_start or 1,
        question=question.prompt,
    )


def answer_payload(attempts: list[Attempt]) -> AnswerResponse:
    return AnswerResponse(
        passed=all(attempt.passed for attempt in attempts),
        results=[
            AnswerResult(
                question_id=attempt.question_id,
                passed=attempt.passed,
                hint=attempt.feedback,
                hint_line=attempt.hint_line,
            )
            for attempt in attempts
        ],
    )


def model_http_error(error: Exception) -> HTTPException:
    if isinstance(error, ModelConfigurationError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error))
    if isinstance(error, ModelRequestError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Anthropic could not process the request. Check ANTHROPIC_API_KEY, MODEL, and Railway's deployment logs.",
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="The question-generation model did not return the expected JSON after one retry.",
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="Dartmouth Gate API", version="1.0.0", lifespan=lifespan)


@app.get("/health", dependencies=[Depends(require_gate_secret)])
def health() -> dict[str, str]:
    return {"status": "ok", "api_version": "v1", "implementation": "anthropic"}


@app.post("/proposals", status_code=status.HTTP_201_CREATED, response_model=ProposalCreateResponse, dependencies=[Depends(require_gate_secret)])
def create_proposal(payload: ProposalInput, session: Session = Depends(get_session)) -> ProposalCreateResponse:
    try:
        generated_questions = generate_questions(payload.code)
    except (ModelConfigurationError, ModelOutputError, ModelRequestError) as error:
        raise model_http_error(error) from error

    proposal = Proposal(
        id=str(uuid4()), repository=payload.repo, file_path=payload.file_path, commit_sha="",
        diff=payload.code, summary=payload.task, status="pending", created_at=utc_now(),
    )
    session.add(proposal)
    questions = [
        Question(
            id=str(uuid4()), proposal_id=proposal.id, prompt=question.prompt, rubric=question.rubric,
            line_start=question.line_start, line_end=question.line_end,
        )
        for question in generated_questions
    ]
    session.add_all(questions)
    session.commit()
    return ProposalCreateResponse(proposal_id=proposal.id, questions=[question_payload(question) for question in questions])


def grade_proposal_result(proposal_id: str, payload: GradeInput, session: Session) -> AnswerResponse:
    proposal = get_proposal_or_404(session, proposal_id)
    if proposal.status in {"passed", "approved"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Proposal has already passed.")
    questions = list(session.scalars(select(Question).where(Question.proposal_id == proposal_id)))
    question_ids = {question.id for question in questions}
    answers_by_question = {answer.question_id: answer.answer for answer in payload.answers}
    if len(answers_by_question) != len(payload.answers) or set(answers_by_question) != question_ids:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Provide exactly one answer for every proposal question.")

    attempts: list[Attempt] = []
    try:
        for question in questions:
            decision = grade_answer(
                proposal.diff,
                GradingQuestion(prompt=question.prompt, rubric=question.rubric),
                answers_by_question[question.id],
            )
            attempt = Attempt(
                id=str(uuid4()), proposal_id=proposal.id, question_id=question.id, answer=answers_by_question[question.id],
                passed=decision.passed, feedback=decision.hint, hint_line=decision.hint_line, created_at=utc_now(),
            )
            session.add(attempt)
            attempts.append(attempt)
    except (ModelConfigurationError, ModelOutputError, ModelRequestError) as error:
        session.rollback()
        raise model_http_error(error) from error

    proposal.status = "passed" if all(attempt.passed for attempt in attempts) else "pending"
    proposal.graded_at = utc_now()
    session.commit()
    return answer_payload(attempts)


@app.post("/proposals/{proposal_id}/answers", response_model=AnswerResponse, dependencies=[Depends(require_gate_secret)])
def submit_answers(proposal_id: str, payload: GradeInput, session: Session = Depends(get_session)) -> AnswerResponse:
    return grade_proposal_result(proposal_id, payload, session)


@app.get("/proposals/{proposal_id}", response_model=ProposalResponse, dependencies=[Depends(require_gate_secret)])
def get_proposal(proposal_id: str, session: Session = Depends(get_session)) -> ProposalResponse:
    proposal = get_proposal_or_404(session, proposal_id)
    attempts = session.scalars(select(Attempt).where(Attempt.proposal_id == proposal.id)).all()
    return ProposalResponse(
        proposal_id=proposal.id,
        repo=proposal.repository,
        file_path=proposal.file_path or "",
        status="passed" if proposal.status in {"passed", "approved"} else "pending",
        attempts=len(attempts),
    )


@app.post("/check", response_model=CheckResponse, dependencies=[Depends(require_gate_secret)])
def check(payload: CheckInput, session: Session = Depends(get_session)) -> CheckResponse:
    added_by_file = parse_added_lines(payload.diff)
    unanswered: list[dict[str, str]] = []
    backend_url = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")

    for file_path, added_lines in added_by_file.items():
        proposals = session.scalars(
            select(Proposal).where(
                Proposal.repository == payload.repo,
                Proposal.file_path == file_path,
                Proposal.status.not_in(["passed", "approved"]),
            )
        )
        for proposal in proposals:
            if proposal_match_ratio(proposal.diff, added_lines) >= 0.5:
                unanswered.append(
                    {
                        "proposal_id": proposal.id,
                        "file_path": file_path,
                        "review_url": f"{backend_url}/review/{proposal.id}",
                    }
                )

    return CheckResponse(status="fail" if unanswered else "pass", unanswered=unanswered)


def render_review_page(
    proposal: Proposal,
    questions: list[Question],
    answers: dict[str, str] | None = None,
    grade: AnswerResponse | None = None,
    error_message: str | None = None,
) -> str:
    answers = answers or {}
    code_lines = proposal.diff.splitlines() or [""]
    code_html = "\n".join(
        f'<span class="line-number">{line_number:04d}</span><span class="code-line">{escape(line)}</span>'
        for line_number, line in enumerate(code_lines, start=1)
    )
    question_html = "\n".join(
        "\n".join(
            [
                '<section class="question">',
                f"<h2>Question {index}</h2>",
                f"<p>{escape(question.prompt)}</p>",
                f'<label for="answer-{escape(question.id)}">Your answer</label>',
                f'<textarea id="answer-{escape(question.id)}" name="answer_{escape(question.id)}" required>{escape(answers.get(question.id, ""))}</textarea>',
                "</section>",
            ]
        )
        for index, question in enumerate(questions, start=1)
    )
    result_html = ""
    if grade is not None:
        passed = grade.passed
        rows = []
        for result in grade.results:
            outcome = "Passed" if result.passed else escape(result.hint)
            css_class = "passed" if result.passed else "failed"
            rows.append(f'<li class="{css_class}">{outcome}</li>')
        heading = "Passed" if passed else "Review needs another answer"
        result_html = f'<section class="result"><h2>{heading}</h2><ul>{"".join(rows)}</ul></section>'
    if error_message:
        result_html = f'<section class="result failed"><h2>Could not grade answers</h2><p>{escape(error_message)}</p></section>'

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Code review · {escape(proposal.file_path or "Proposed file")}</title>
<style>
body {{ margin: 0; background: #f7f8fa; color: #202124; font: 16px/1.5 system-ui, sans-serif; }}
main {{ max-width: 980px; margin: 0 auto; padding: 40px 20px 64px; }}
h1 {{ margin: 0; font-size: 28px; }} .path {{ color: #52606d; margin: 4px 0 28px; }}
.code {{ background: #18212b; border-radius: 10px; color: #e7edf3; overflow-x: auto; padding: 16px 0; }}
.code pre {{ margin: 0; font: 13px/1.55 ui-monospace, Consolas, monospace; }}
.line-number {{ color: #8b9bab; display: inline-block; padding: 0 16px; text-align: right; user-select: none; width: 4ch; }}
.code-line {{ white-space: pre; }} .question, .result {{ background: white; border: 1px solid #dfe3e8; border-radius: 10px; margin-top: 20px; padding: 20px; }}
.question h2, .result h2 {{ font-size: 18px; margin: 0 0 8px; }} label {{ display: block; font-weight: 600; margin-top: 14px; }}
textarea {{ border: 1px solid #aeb8c2; border-radius: 6px; box-sizing: border-box; font: inherit; min-height: 96px; padding: 10px; resize: vertical; width: 100%; }}
button {{ background: #1455a3; border: 0; border-radius: 6px; color: white; cursor: pointer; font: inherit; font-weight: 600; margin-top: 20px; padding: 10px 16px; }}
.passed {{ color: #16713d; }} .failed {{ color: #a33a31; }} .result ul {{ margin: 8px 0 0; padding-left: 20px; }}
</style></head><body><main>
<h1>Code understanding review</h1><p class="path">{escape(proposal.file_path or "Proposed file")}</p>
<section class="code"><pre>{code_html}</pre></section>
{result_html}
<form method="post" action="/review/{escape(proposal.id)}/answers">{question_html}<button type="submit">Submit answers</button></form>
</main></body></html>"""


@app.get("/review/{proposal_id}", response_class=HTMLResponse)
def review_page(proposal_id: str, session: Session = Depends(get_session)) -> HTMLResponse:
    proposal = get_proposal_or_404(session, proposal_id)
    questions = list(session.scalars(select(Question).where(Question.proposal_id == proposal.id)))
    return HTMLResponse(render_review_page(proposal, questions))


@app.post("/review/{proposal_id}/answers", response_class=HTMLResponse)
async def submit_review_answers(proposal_id: str, request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    proposal = get_proposal_or_404(session, proposal_id)
    questions = list(session.scalars(select(Question).where(Question.proposal_id == proposal.id)))
    form_values = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    answers = {question.id: form_values.get(f"answer_{question.id}", [""])[0] for question in questions}
    if any(not answer.strip() for answer in answers.values()):
        return HTMLResponse(render_review_page(proposal, questions, answers, error_message="Answer every question before submitting."), status_code=422)
    try:
        grade = grade_proposal_result(
            proposal.id,
            GradeInput(answers=[AnswerInput(question_id=question.id, answer=answers[question.id]) for question in questions]),
            session,
        )
    except HTTPException as error:
        return HTMLResponse(render_review_page(proposal, questions, answers, error_message=str(error.detail)), status_code=error.status_code)
    return HTMLResponse(render_review_page(proposal, questions, answers, grade=grade))
