"""Dartmouth's FastAPI gate backed by Anthropic question generation and grading."""

from __future__ import annotations

import hmac
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, TypeVar
from uuid import uuid4

from anthropic import APIError, Anthropic
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    proposal: Mapped[Proposal] = relationship(back_populates="attempts")
    question: Mapped[Question] = relationship(back_populates="attempts")


class ProposalInput(BaseModel):
    repository: str = Field(min_length=1)
    file_path: str | None = Field(default=None, min_length=1)
    commit_sha: str = Field(min_length=1)
    diff: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class AnswerInput(BaseModel):
    question_id: str = Field(min_length=1)
    answer: str = Field(min_length=1)


class GradeInput(BaseModel):
    answers: list[AnswerInput] = Field(min_length=1)


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
    questions: list[GeneratedQuestion] = Field(min_length=1, max_length=3)


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
    feedback: str = Field(min_length=1)


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
    """Create fresh tables and add the file-path column to pre-existing databases."""
    Base.metadata.create_all(bind=engine)
    columns = {column["name"] for column in inspect(engine).get_columns("proposals")}
    if "file_path" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE proposals ADD COLUMN file_path VARCHAR(1024)"))


def load_prompt(name: str) -> str:
    try:
        return (PROMPTS_DIRECTORY / name).read_text(encoding="utf-8")
    except OSError as error:
        raise ModelConfigurationError(f"Prompt file {name} could not be read.") from error


def _call_anthropic(system_prompt: str, user_content: str) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    model = os.getenv("MODEL")
    if not api_key or not model:
        raise ModelConfigurationError("ANTHROPIC_API_KEY and MODEL must be configured.")
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
            return output_type.model_validate_json(raw_output)
        except ValidationError as error:
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
    feedback = result.feedback or result.hint
    if not feedback:
        feedback = "Answer passed review." if result.passed else "Answer did not satisfy the grading rubric."
    if result.hint_line is not None:
        feedback = f"{feedback} See line {result.hint_line:04d}."
    return GradedAnswer(passed=result.passed, feedback=feedback)


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


def question_payload(question: Question) -> dict[str, str]:
    """The client sees the question but never the stored rubric."""
    return {"question_id": question.id, "prompt": question.prompt}


def grade_payload(proposal: Proposal, attempts: list[Attempt]) -> dict[str, object] | None:
    if proposal.graded_at is None:
        return None
    return {
        "proposal_id": proposal.id,
        "status": proposal.status,
        "results": [
            {"question_id": attempt.question_id, "passed": attempt.passed, "feedback": attempt.feedback}
            for attempt in attempts
        ],
        "graded_at": proposal.graded_at,
    }


def model_http_error(error: Exception) -> HTTPException:
    if isinstance(error, ModelConfigurationError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error))
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="The grading model returned an invalid response.")


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="Dartmouth Gate API", version="1.0.0", lifespan=lifespan, dependencies=[Depends(require_gate_secret)])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "api_version": "v1", "implementation": "anthropic"}


@app.post("/v1/proposals", status_code=status.HTTP_201_CREATED)
def create_proposal(payload: ProposalInput, session: Session = Depends(get_session)) -> dict[str, object]:
    try:
        generated_questions = generate_questions(payload.diff)
    except (ModelConfigurationError, ModelOutputError, ModelRequestError) as error:
        raise model_http_error(error) from error

    proposal = Proposal(
        id=str(uuid4()), repository=payload.repository, file_path=payload.file_path,
        commit_sha=payload.commit_sha, diff=payload.diff,
        summary=payload.summary, status="pending", created_at=utc_now(),
    )
    session.add(proposal)
    session.add_all([
        Question(id=str(uuid4()), proposal_id=proposal.id, prompt=question.prompt, rubric=question.rubric)
        for question in generated_questions
    ])
    session.commit()
    return {
        "proposal_id": proposal.id, "repository": proposal.repository, "commit_sha": proposal.commit_sha,
        "status": proposal.status, "created_at": proposal.created_at,
    }


@app.get("/v1/proposals/{proposal_id}/questions")
def get_questions(proposal_id: str, session: Session = Depends(get_session)) -> dict[str, object]:
    get_proposal_or_404(session, proposal_id)
    questions = list(session.scalars(select(Question).where(Question.proposal_id == proposal_id)))
    return {"proposal_id": proposal_id, "questions": [question_payload(question) for question in questions]}


@app.post("/v1/proposals/{proposal_id}/grade")
def grade_proposal(proposal_id: str, payload: GradeInput, session: Session = Depends(get_session)) -> dict[str, object]:
    proposal = get_proposal_or_404(session, proposal_id)
    if proposal.graded_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Proposal has already been graded.")
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
                passed=decision.passed, feedback=decision.feedback, created_at=utc_now(),
            )
            session.add(attempt)
            attempts.append(attempt)
    except (ModelConfigurationError, ModelOutputError, ModelRequestError) as error:
        session.rollback()
        raise model_http_error(error) from error

    proposal.status = "approved" if all(attempt.passed for attempt in attempts) else "rejected"
    proposal.graded_at = utc_now()
    session.commit()
    return grade_payload(proposal, attempts)  # type: ignore[return-value]


@app.get("/v1/proposals/{proposal_id}/log")
def get_proposal_log(proposal_id: str, session: Session = Depends(get_session)) -> dict[str, object]:
    proposal = get_proposal_or_404(session, proposal_id)
    events: list[dict[str, object]] = [{
        "sequence": 1, "type": "proposal.created", "at": proposal.created_at, "data": {"status": "pending"},
    }]
    if proposal.graded_at is not None:
        attempts = list(session.scalars(select(Attempt).where(Attempt.proposal_id == proposal.id)))
        events.append({"sequence": 2, "type": "proposal.graded", "at": proposal.graded_at, "data": grade_payload(proposal, attempts)})
    return {"proposal_id": proposal.id, "events": events}


@app.get("/v1/proposals/{proposal_id}")
def get_proposal(proposal_id: str, session: Session = Depends(get_session)) -> dict[str, object]:
    proposal = get_proposal_or_404(session, proposal_id)
    questions = list(session.scalars(select(Question).where(Question.proposal_id == proposal.id)))
    attempts = list(session.scalars(select(Attempt).where(Attempt.proposal_id == proposal.id)))
    return {
        "proposal_id": proposal.id, "repository": proposal.repository, "commit_sha": proposal.commit_sha,
        "status": proposal.status, "created_at": proposal.created_at,
        "questions": [question_payload(question) for question in questions], "grade": grade_payload(proposal, attempts),
    }


class CheckInput(BaseModel):
    repo: str = Field(min_length=1)
    diff: str = Field(min_length=1)


@app.post("/check")
def check(payload: CheckInput, session: Session = Depends(get_session)) -> dict[str, object]:
    added_by_file = parse_added_lines(payload.diff)
    unanswered: list[dict[str, str]] = []
    backend_url = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")

    for file_path, added_lines in added_by_file.items():
        proposals = session.scalars(
            select(Proposal).where(
                Proposal.repository == payload.repo,
                Proposal.file_path == file_path,
                Proposal.status != "passed",
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

    return {"status": "fail" if unanswered else "pass", "unanswered": unanswered}
