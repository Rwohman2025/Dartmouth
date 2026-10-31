"""Ask the Dartmouth backend whether this pull request needs review."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def require_environment(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required environment variable {name} is missing.")
    return value


def pull_request_context() -> tuple[str, str, int]:
    """Return the base SHA, head SHA, and number from GitHub's event file."""
    event_path = Path(require_environment("GITHUB_EVENT_PATH"))
    event = json.loads(event_path.read_text(encoding="utf-8"))
    try:
        pull_request = event["pull_request"]
        return pull_request["base"]["sha"], pull_request["head"]["sha"], event["number"]
    except (KeyError, TypeError) as error:
        raise RuntimeError("This workflow must run for a pull_request event.") from error


def pull_request_diff(base_sha: str, head_sha: str) -> str:
    completed = subprocess.run(
        ["git", "diff", "--no-ext-diff", "--unified=0", base_sha, head_sha],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def backend_check_url(backend_url: str) -> str:
    base_url = backend_url.rstrip("/")
    return base_url if base_url.endswith("/check") else f"{base_url}/check"


def post_json(url: str, payload: dict[str, str], gate_secret: str) -> dict[str, object]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Gate-Secret": gate_secret,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        raise RuntimeError(f"Backend check failed with HTTP {error.code}.") from error
    except URLError as error:
        raise RuntimeError("Could not reach BACKEND_URL.") from error
    try:
        data = json.loads(body)
    except json.JSONDecodeError as error:
        raise RuntimeError("Backend /check did not return JSON.") from error
    if not isinstance(data, dict):
        raise RuntimeError("Backend /check returned an unexpected response.")
    return data


def failure_comment(unanswered: list[object]) -> str:
    lines = ["## Comprehension Gate", "", "This pull request has unanswered code-review questions:", ""]
    for item in unanswered:
        if not isinstance(item, dict):
            continue
        file_path = item.get("file_path")
        review_url = item.get("review_url")
        if isinstance(file_path, str) and isinstance(review_url, str):
            lines.append(f"- [`{file_path}`]({review_url})")
    lines.extend(["", "Open each link, answer the question, then push your update."])
    return "\n".join(lines)


def post_pull_request_comment(repo: str, pull_number: int, body: str, github_token: str) -> None:
    request = Request(
        f"https://api.github.com/repos/{repo}/issues/{pull_number}/comments",
        data=json.dumps({"body": body}).encode("utf-8"),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {github_token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30):
            pass
    except HTTPError as error:
        raise RuntimeError(f"Could not post the pull-request comment (HTTP {error.code}).") from error
    except URLError as error:
        raise RuntimeError("Could not reach the GitHub API to post the pull-request comment.") from error


def main() -> int:
    backend_url = require_environment("BACKEND_URL")
    gate_secret = require_environment("GATE_SECRET")
    repo = require_environment("GITHUB_REPOSITORY")
    github_token = require_environment("GITHUB_TOKEN")
    base_sha, head_sha, pull_number = pull_request_context()
    diff = pull_request_diff(base_sha, head_sha)
    result = post_json(backend_check_url(backend_url), {"repo": repo, "diff": diff}, gate_secret)

    status = result.get("status")
    if status == "pass":
        print("Comprehension Gate passed.")
        return 0
    if status != "fail":
        raise RuntimeError("Backend /check returned an unknown status.")

    unanswered = result.get("unanswered")
    if not isinstance(unanswered, list):
        raise RuntimeError("Backend /check returned an invalid unanswered list.")
    post_pull_request_comment(repo, pull_number, failure_comment(unanswered), github_token)
    print("Comprehension Gate found unanswered questions. A pull-request comment was posted.")
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Comprehension Gate error: {error}", file=sys.stderr)
        raise SystemExit(1)
