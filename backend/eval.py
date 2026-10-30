"""Evaluate Anthropic question generation and grading against the demo answer key."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from main import REPOSITORY_ROOT, generate_questions, grade_answer


@dataclass(frozen=True)
class AnswerPair:
    good: str
    bad: str


def load_answer_key(path: Path) -> dict[str, AnswerPair]:
    content = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"## \d+\. `(?P<filename>[^`]+)`.*?"
        r"- \*\*Good answer:\*\* \"(?P<good>.*?)\"\s*"
        r"- \*\*Bad answer:\*\* \"(?P<bad>.*?)\"",
        re.DOTALL,
    )
    answer_key = {
        match.group("filename"): AnswerPair(good=match.group("good"), bad=match.group("bad"))
        for match in pattern.finditer(content)
    }
    if not answer_key:
        raise ValueError("No good/bad answer pairs were found in ANSWER_KEY.md.")
    return answer_key


def render_table(rows: list[tuple[str, str, bool, bool]]) -> None:
    headers = ("snippet", "question", "good passed", "bad passed")
    display_rows = [(snippet, question, str(good), str(bad)) for snippet, question, good, bad in rows]
    widths = [max(len(header), *(len(row[index]) for row in display_rows)) for index, header in enumerate(headers)]
    print(" | ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("-+-".join("-" * width for width in widths))
    for row in display_rows:
        print(" | ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def main() -> None:
    snippets_directory = REPOSITORY_ROOT / "demo" / "snippets"
    answer_key = load_answer_key(REPOSITORY_ROOT / "demo" / "ANSWER_KEY.md")
    rows: list[tuple[str, str, bool, bool]] = []
    for snippet_path in sorted(snippets_directory.iterdir()):
        if not snippet_path.is_file():
            continue
        answers = answer_key.get(snippet_path.name)
        if answers is None:
            raise ValueError(f"No answer key entry for {snippet_path.name}.")
        code = snippet_path.read_text(encoding="utf-8")
        for question in generate_questions(code):
            good_result = grade_answer(code, question, answers.good)
            bad_result = grade_answer(code, question, answers.bad)
            rows.append((snippet_path.name, question.prompt, good_result.passed, bad_result.passed))
    render_table(rows)


if __name__ == "__main__":
    main()
