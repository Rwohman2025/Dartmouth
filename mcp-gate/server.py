import asyncio
import hashlib
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import AcceptedElicitation
from mcp.types import (
    ClientCapabilities,
    ElicitationCapability,
    ElicitRequest,
    ElicitRequestFormParams,
    InputRequiredResult,
)
from mcp_types.version import MODERN_PROTOCOL_VERSIONS

# BACKEND_URL and GATE_SECRET come from the .env in the repo root. Real
# environment variables win over the file (override=False).
load_dotenv(Path(__file__).parent.parent / ".env")

mcp = FastMCP("mcp-gate")

QUESTION = "What is 2 + 2?"
ANSWER_KEY = "answer"
SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "string", "title": "Answer"}},
    "required": ["value"],
}


def _answer_text(action: str, content: dict | None) -> str:
    if action == "accept" and content:
        return str(content.get("value", ""))
    return f"User did not answer (action: {action})."


@mcp.tool
async def ask_test(ctx: Context) -> str | InputRequiredResult:
    """Ask the user "What is 2 + 2?" via elicitation and return what they typed."""
    rc = ctx.request_context
    modern = rc is not None and rc.protocol_version in MODERN_PROTOCOL_VERSIONS

    if modern:
        # 2026-07-28 era: no server-initiated requests. Return input_requests,
        # the client prompts the user and re-calls the tool with input_responses.
        responses = ctx.input_responses
        if responses and ANSWER_KEY in responses:
            resp = responses[ANSWER_KEY]
            return _answer_text(resp.action, resp.content)
        return InputRequiredResult(
            input_requests={
                ANSWER_KEY: ElicitRequest(
                    params=ElicitRequestFormParams(
                        message=QUESTION, requested_schema=SCHEMA
                    )
                )
            }
        )

    # Handshake era: classic server-initiated elicitation.
    supported = ctx.session.check_client_capability(
        ClientCapabilities(elicitation=ElicitationCapability())
    )
    if not supported:
        raise ToolError(
            "This MCP client does not support elicitation, so ask_test cannot "
            "prompt the user. Use a client that advertises the elicitation capability."
        )
    result = await ctx.elicit(QUESTION, response_type=str)
    if isinstance(result, AcceptedElicitation):
        return result.data
    return f"User did not answer (action: {result.action})."


# --------------------------------------------------------------------------
# propose_write: comprehension gate in front of file writes
# --------------------------------------------------------------------------

MAX_ATTEMPTS = 3
FORM_KEY = "gate_form"
PENDING_DIR = ".pending"
ANSWER_KEY_PATH = Path(__file__).parent.parent / "demo" / "ANSWER_KEY.md"
MOCK_MIN_KEYWORD_HITS = 3
STOPWORDS = {
    "about", "after", "because", "before", "being", "could", "every", "their",
    "there", "these", "those", "which", "while", "would", "other", "where",
    "should", "since", "still", "than", "that", "this", "with", "from", "have",
}

REFUSAL = (
    "The user has not shown that they understand this change, so {file} was NOT "
    "written ({why}). Do not try to write this file another way: no other tool, "
    "shell command, or retry of propose_write. Tell the user the write was "
    "blocked and let them decide how to proceed."
)


def _mock_backend() -> bool:
    return os.environ.get("MOCK_BACKEND") == "1"


def _run(cmd: list[str], cwd: Path) -> str:
    try:
        out = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, check=True, timeout=20
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
        detail = getattr(e, "stderr", None) or str(e)
        raise ToolError(f"`{' '.join(cmd)}` failed in {cwd}: {detail.strip()}")
    return out.stdout.strip()


def _locate(file_path: str) -> tuple[Path, str, str]:
    """Return (repo root, path relative to root with forward slashes, owner/name)."""
    target = Path(file_path)
    if not target.is_absolute():
        target = Path.cwd() / target
    cwd = target.parent
    while not cwd.exists() and cwd != cwd.parent:
        cwd = cwd.parent

    root = Path(_run(["git", "rev-parse", "--show-toplevel"], cwd)).resolve()
    try:
        rel = target.resolve().relative_to(root).as_posix()
    except ValueError:
        raise ToolError(f"{file_path} is outside the git repo at {root}.")
    if rel.split("/")[0] in (PENDING_DIR, ".git"):
        raise ToolError(f"{rel} is not a file propose_write may create or change.")

    try:
        url = _run(["git", "remote", "get-url", "origin"], root)
    except ToolError:
        if not _mock_backend():
            raise
        return root, rel, f"mock/{root.name}"
    m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?/?$", url)
    if not m:
        raise ToolError(f"Cannot read owner/name from remote URL: {url}")
    return root, rel, m.group(1)


def _pending_path(root: Path, rel: str) -> Path:
    return root / PENDING_DIR / rel


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="")


def _clear_pending(root: Path, rel: str) -> None:
    path = _pending_path(root, rel)
    path.unlink(missing_ok=True)
    stop = root / PENDING_DIR
    for parent in path.parents:
        try:
            parent.rmdir()
        except OSError:
            break
        if parent == stop:
            break


def _fmt_range(start: int, end: int) -> str:
    return f"line {start}" if start == end else f"lines {start}-{end}"


# --- mock backend (demo/ANSWER_KEY.md) -------------------------------------


def _load_answer_key() -> dict[str, dict]:
    text = ANSWER_KEY_PATH.read_text(encoding="utf-8")
    entries: dict[str, dict] = {}
    for sec in re.split(r"^## ", text, flags=re.M)[1:]:
        name = re.match(r"\d+\.\s+`([^`]+)`", sec)
        line = re.search(r"\*\*Line:\*\*\s*(\d+)", sec)
        question = re.search(r'\*\*Question that catches it:\*\*\s*"(.+?)"\s*$', sec, re.M)
        good = re.search(r'\*\*Good answer:\*\*\s*"(.+?)"\s*$', sec, re.M)
        if name and line and question and good:
            entries[name.group(1)] = {
                "line": int(line.group(1)),
                "question": question.group(1),
                "good": good.group(1),
            }
    return entries


def _keywords(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9_.]+", text.lower())
    return {w.strip(".") for w in words if len(w.strip(".")) >= 5} - STOPWORDS


def _mock_snippet(rel: str) -> tuple[str, dict]:
    entries = _load_answer_key()
    name = rel.rsplit("/", 1)[-1]
    if name not in entries:
        raise ToolError(
            f"MOCK_BACKEND has no snippet for {name}. Known: {', '.join(entries)}."
        )
    return name, entries[name]


# --- backend calls ----------------------------------------------------------
# Shapes follow CONTRACT.md and are confined to _create_proposal and
# _submit_answers. Internally, answers are {question_id: text} and a hint is
# {question_id, hint, hint_line}.
#   POST /proposals               {repo, file_path, code, task}
#                                 -> {proposal_id, questions: [{id, line_start, line_end, question}]}
#   POST /proposals/{id}/answers  {answers: [{question_id, answer}]}
#                                 -> {passed, results: [{question_id, passed, hint, hint_line}]}


def _http_post(path: str, body: dict) -> dict:
    base, secret = os.environ.get("BACKEND_URL"), os.environ.get("GATE_SECRET")
    if not base or not secret:
        raise ToolError(
            "BACKEND_URL and GATE_SECRET must be set in the server's environment "
            "(or set MOCK_BACKEND=1 to test without a backend)."
        )
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Gate-Secret": secret},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raise ToolError(f"Backend {path} returned HTTP {e.code}: {e.read()[:300]!r}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise ToolError(f"Backend {path} failed: {e}")


async def _create_proposal(repo: str, rel: str, content: str, task: str) -> dict:
    if _mock_backend():
        name, entry = _mock_snippet(rel)
        return {
            "id": f"mock-{name}",
            "questions": [
                {
                    "id": "q1",
                    "line_start": entry["line"],
                    "line_end": entry["line"],
                    "question": entry["question"],
                }
            ],
        }
    data = await asyncio.to_thread(
        _http_post,
        "/proposals",
        {"repo": repo, "file_path": rel, "code": content, "task": task},
    )
    return {"id": data["proposal_id"], "questions": data["questions"]}


async def _submit_answers(state: dict, answers: dict) -> tuple[bool, list[dict]]:
    if _mock_backend():
        _, entry = _mock_snippet(state["rel"])
        hits = _keywords(answers.get("q1", "")) & _keywords(entry["good"])
        if len(hits) >= MOCK_MIN_KEYWORD_HITS:
            return True, []
        hint = (
            "Trace the exact input from the question through the code, one "
            "line at a time, before answering."
        )
        return False, [{"question_id": "q1", "hint": hint, "hint_line": entry["line"]}]
    data = await asyncio.to_thread(
        _http_post,
        f"/proposals/{state['id']}/answers",
        {"answers": [{"question_id": q, "answer": a} for q, a in answers.items()]},
    )
    hints = [
        {"question_id": r["question_id"], "hint": r["hint"], "hint_line": r.get("hint_line")}
        for r in data.get("results") or []
        if not r.get("passed") and r.get("hint")
    ]
    return bool(data["passed"]), hints


# --- form + state machine ---------------------------------------------------


def _form(state: dict, hints: list[dict] | None = None) -> tuple[str, dict]:
    pending = f"{PENDING_DIR}/{state['rel']}"
    message = (
        f"Attempt {state['attempt']} of {MAX_ATTEMPTS}. "
        f"Open {pending} in {state['root']} to read the proposed code with line "
        f"numbers, then answer each question below.\n"
        f"Task: {state['task']}"
    )
    by_q = {h["question_id"]: h for h in hints or []}
    props = {}
    for q in state["questions"]:
        desc = f"{q['question']} ({_fmt_range(q['line_start'], q['line_end'])})"
        hint = by_q.get(q["id"])
        if hint:
            desc += f"\nHint: {hint['hint']}"
            if hint.get("hint_line") is not None:
                desc += f" (line {hint['hint_line']})"
        props[q["id"]] = {
            "type": "string",
            "title": f"Question {len(props) + 1}",
            "description": desc,
        }
    schema = {"type": "object", "properties": props, "required": list(props)}
    return message, schema


def _sha(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def _start(file_path: str, content: str, task: str) -> dict:
    root, rel, repo = _locate(file_path)
    _write_file(_pending_path(root, rel), content)
    try:
        proposal = await _create_proposal(repo, rel, content, task)
    except BaseException:
        _clear_pending(root, rel)
        raise
    return {
        "id": proposal["id"],
        "questions": proposal["questions"],
        "attempt": 1,
        "root": str(root),
        "rel": rel,
        "task": task,
        "sha": _sha(content),
    }


def _refuse(state: dict, why: str) -> str:
    _clear_pending(Path(state["root"]), state["rel"])
    return REFUSAL.format(file=state["rel"], why=why)


async def _grade(
    state: dict, content: str, answers: dict
) -> tuple[str | None, list[dict]]:
    """Return (final message, hints). The message is None when the user may retry."""
    if _sha(content) != state["sha"]:
        return _refuse(state, "the content changed after the user was quizzed on it"), []
    passed, hints = await _submit_answers(state, answers)
    root, rel = Path(state["root"]), state["rel"]
    if passed:
        _write_file(root / rel, content)
        _clear_pending(root, rel)
        return f"Understanding confirmed. Wrote {rel}.", []
    if state["attempt"] >= MAX_ATTEMPTS:
        return _refuse(state, f"{MAX_ATTEMPTS} failed attempts"), []
    state["attempt"] += 1
    return None, hints


@mcp.tool
async def propose_write(
    file_path: str, content: str, task: str, ctx: Context
) -> str | InputRequiredResult:
    """Create or change a file. ALWAYS use this tool to create or change any
    file; never write files any other way (no Write/Edit tools, no shell
    redirects), including when this tool refuses.

    The user is first asked questions about the code to confirm they
    understand it. The file is written only if they answer well enough.

    Args:
        file_path: Absolute path of the file to create or change (inside a git repo).
        content: The complete new contents of the file.
        task: One sentence on what the change is for.
    """
    rc = ctx.request_context
    modern = rc is not None and rc.protocol_version in MODERN_PROTOCOL_VERSIONS

    if modern:
        # No server-initiated requests: each round returns an InputRequiredResult
        # carrying the attempt state, and the client re-calls with the answers.
        responses, raw = ctx.input_responses, ctx.request_state
        resp = responses.get(FORM_KEY) if responses else None
        if resp is None or raw is None:
            state = await _start(file_path, content, task)
            hints = None
        else:
            state = json.loads(raw)
            if resp.action != "accept" or not resp.content:
                return _refuse(state, f"user chose {resp.action}")
            final, hints = await _grade(state, content, resp.content)
            if final is not None:
                return final
        message, schema = _form(state, hints)
        return InputRequiredResult(
            input_requests={
                FORM_KEY: ElicitRequest(
                    params=ElicitRequestFormParams(
                        message=message, requested_schema=schema
                    )
                )
            },
            request_state=json.dumps(state),
        )

    if not ctx.session.check_client_capability(
        ClientCapabilities(elicitation=ElicitationCapability())
    ):
        raise ToolError(
            "This MCP client does not support elicitation, so propose_write "
            "cannot ask the user questions. The file was not written."
        )
    state = await _start(file_path, content, task)
    hints = None
    while True:
        message, schema = _form(state, hints)
        result = await ctx.session.elicit_form(message, schema)
        if result.action != "accept" or not result.content:
            return _refuse(state, f"user chose {result.action}")
        final, hints = await _grade(state, content, result.content)
        if final is not None:
            return final


if __name__ == "__main__":
    mcp.run()
