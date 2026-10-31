import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).with_name("check.py")
SPEC = importlib.util.spec_from_file_location("gate_check", SCRIPT)
check = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(check)


def test_backend_check_url_adds_the_endpoint_once():
    assert check.backend_check_url("https://gate.example") == "https://gate.example/check"
    assert check.backend_check_url("https://gate.example/") == "https://gate.example/check"
    assert check.backend_check_url("https://gate.example/check") == "https://gate.example/check"


def test_failure_comment_lists_each_file_and_review_link():
    comment = check.failure_comment(
        [
            {"file_path": "src/scores.py", "review_url": "https://gate.example/review/one"},
            {"file_path": "src/users.py", "review_url": "https://gate.example/review/two"},
        ]
    )
    assert "[`src/scores.py`](https://gate.example/review/one)" in comment
    assert "[`src/users.py`](https://gate.example/review/two)" in comment
