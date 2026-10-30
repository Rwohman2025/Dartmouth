"""Dartmouth's local, database-backed FastAPI gate.

The question prompts and grading rule are intentionally fake for this stage.
"""

from __future__ import annotations

import hmac
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
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
    commit_sha: str = Field(min_length=1)
    diff: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class AnswerInput(BaseModel):
    question_id: str = Field(min_length=1)
    answer: str = Field(min_length=1)


class GradeInput(BaseModel):
    answers: list[AnswerInput] = Field(min_length=1)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def require_gate_secret(x_gate_secret: str | None = Header(default=None)) -> None:
    expected_secret = os.getenv("GATE_SECRET")
    if not expected_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GATE_SECRET is not configured.",
        )
    if not x_gate_secret or not hmac.compare_digest(x_gate_secret, expected_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid X-Gate-Secret.")


def get_proposal_or_404(session: Session, proposal_id: str) -> Proposal:
    proposal = session.get(Proposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found.")
    return proposal


def question_payload(question: Question) -> dict[str, str]:
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


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Dartmouth Gate API",
    version="1.0.0",
    lifespan=lifespan,
    dependencies=[Depends(require_gate_secret)],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "api_version": "v1", "implementation": "fake-data"}


@app.post("/v1/proposals", status_code=status.HTTP_201_CREATED)
def create_proposal(payload: ProposalInput, session: Session = Depends(get_session)) -> dict[str, object]:
    created_at = utc_now()
    proposal = Proposal(
        id=str(uuid4()),
        repository=payload.repository,
        commit_sha=payload.commit_sha,
        diff=payload.diff,
        summary=payload.summary,
        status="pending",
        created_at=created_at,
    )
    session.add(proposal)
    session.add_all(
        [
            Question(
                id=str(uuid4()),
                proposal_id=proposal.id,
                prompt="What behavior changes at the boundary of this proposal?",
                rubric="Fake rubric: the answer must contain more than 20 characters.",
            ),
            Question(
                id=str(uuid4()),
                proposal_id=proposal.id,
                prompt="What evidence would show that this proposal is safe to merge?",
                rubric="Fake rubric: the answer must contain more than 20 characters.",
            ),
        ]
    )
    session.commit()
    return {
        "proposal_id": proposal.id,
        "repository": proposal.repository,
        "commit_sha": proposal.commit_sha,
        "status": proposal.status,
        "created_at": proposal.created_at,
    }


@app.get("/v1/proposals/{proposal_id}/questions")
def get_questions(proposal_id: str, session: Session = Depends(get_session)) -> dict[str, object]:
    get_proposal_or_404(session, proposal_id)
    questions = list(session.scalars(select(Question).where(Question.proposal_id == proposal_id)))
    return {"proposal_id": proposal_id, "questions": [question_payload(question) for question in questions]}


@app.post("/v1/proposals/{proposal_id}/grade")
def grade_proposal(
    proposal_id: str, payload: GradeInput, session: Session = Depends(get_session)
) -> dict[str, object]:
    proposal = get_proposal_or_404(session, proposal_id)
    if proposal.graded_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Proposal has already been graded.")

    questions = list(session.scalars(select(Question).where(Question.proposal_id == proposal_id)))
    question_ids = {question.id for question in questions}
    answers_by_question = {answer.question_id: answer.answer for answer in payload.answers}
    if len(answers_by_question) != len(payload.answers) or set(answers_by_question) != question_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide exactly one answer for every proposal question.",
        )

    attempts: list[Attempt] = []
    for question in questions:
        answer = answers_by_question[question.id]
        passed = len(answer.strip()) > 20
        feedback = "Fake grader: answer is longer than 20 characters." if passed else "Fake grader: answer must be longer than 20 characters."
        attempt = Attempt(
            id=str(uuid4()),
            proposal_id=proposal.id,
            question_id=question.id,
            answer=answer,
            passed=passed,
            feedback=feedback,
            created_at=utc_now(),
        )
        session.add(attempt)
        attempts.append(attempt)

    proposal.status = "approved" if all(attempt.passed for attempt in attempts) else "rejected"
    proposal.graded_at = utc_now()
    session.commit()
    return grade_payload(proposal, attempts)  # type: ignore[return-value]


@app.get("/v1/proposals/{proposal_id}/log")
def get_proposal_log(proposal_id: str, session: Session = Depends(get_session)) -> dict[str, object]:
    proposal = get_proposal_or_404(session, proposal_id)
    events: list[dict[str, object]] = [
        {
            "sequence": 1,
            "type": "proposal.created",
            "at": proposal.created_at,
            "data": {"status": "pending"},
        }
    ]
    if proposal.graded_at is not None:
        attempts = list(session.scalars(select(Attempt).where(Attempt.proposal_id == proposal.id)))
        events.append(
            {
                "sequence": 2,
                "type": "proposal.graded",
                "at": proposal.graded_at,
                "data": grade_payload(proposal, attempts),
            }
        )
    return {"proposal_id": proposal.id, "events": events}


@app.get("/v1/proposals/{proposal_id}")
def get_proposal(proposal_id: str, session: Session = Depends(get_session)) -> dict[str, object]:
    proposal = get_proposal_or_404(session, proposal_id)
    questions = list(session.scalars(select(Question).where(Question.proposal_id == proposal.id)))
    attempts = list(session.scalars(select(Attempt).where(Attempt.proposal_id == proposal.id)))
    return {
        "proposal_id": proposal.id,
        "repository": proposal.repository,
        "commit_sha": proposal.commit_sha,
        "status": proposal.status,
        "created_at": proposal.created_at,
        "questions": [question_payload(question) for question in questions],
        "grade": grade_payload(proposal, attempts),
    }


@app.get("/check")
def check() -> dict[str, bool]:
    """Temporary action-facing endpoint. It intentionally always passes."""
    return {"pass": True}
