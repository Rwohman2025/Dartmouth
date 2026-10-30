# API Contract

Backend URL: https://dartmouth-production.up.railway.app/docs#/
 until deployed, then replace with the live URL.

All requests and responses are JSON.
Every endpoint except GET /review/{id} requires the header X-Gate-Secret,
whose value comes from the GATE_SECRET environment variable.
file_path is always relative to the repo root (src/utils.py),
never a full path on someone's laptop.
repo is the GitHub name, for example team-name/demo-repo.

## POST /proposals
Request:  {"repo": "...", "file_path": "...", "code": "full proposed file", "task": "what the user asked the agent to do"}
Response: {"proposal_id": "...", "questions": [{"id": "q1", "line_start": 10, "line_end": 14, "question": "..."}]}
The grading rubric is stored on the server and is NEVER returned.

## POST /proposals/{proposal_id}/answers
Request:  {"answers": [{"question_id": "q1", "answer": "..."}]}
Response: {"passed": false, "results": [{"question_id": "q1", "passed": false, "hint": "...", "hint_line": 12}]}
passed is true only when every question passes.
Hints point the user where to look. They never contain the answer.

## GET /proposals/{proposal_id}
Response: {"proposal_id": "...", "repo": "...", "file_path": "...", "status": "pending" or "passed", "attempts": 2}

## POST /check
Request:  {"repo": "...", "diff": "unified diff of the pull request"}
Response: {"status": "pass" or "fail", "unanswered": [{"proposal_id": "...", "file_path": "...", "review_url": "..."}]}
Matching rule: strip whitespace from each line and skip blank lines.
A proposal is flagged when 50% or more of its lines appear in the
added lines of the diff for the same repo and file_path,
and its status is not passed.

## GET /review/{proposal_id}
An HTML page showing the code with line numbers and the questions.
Submitting answers uses the same grading as POST /answers.

## Environment variables
ANTHROPIC_API_KEY  backend only
GATE_SECRET        backend, gate, and GitHub Action
BACKEND_URL        gate and GitHub Action
MODEL              backend only, default claude-sonnet-5-5

## Changing this file
Only change it after agreeing with your partner out loud.
Commit and push the change immediately.