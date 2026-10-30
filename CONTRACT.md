# API agreement — draft v1

Owners: Person A (MCP client/server), Person B (HTTP backend and Action).
Status: agreed starting shape for implementation; only `/health` is implemented.
Changes to fields, routes, tool names, or semantics must update both consumers and this document in the same change.

## Transport and authentication

Backend default: `http://127.0.0.1:8000`. API prefix: `/v1`. JSON requests and responses use `Content-Type: application/json`. IDs are opaque strings; timestamps are RFC 3339 UTC. Examples use illustrative IDs.

Planned API authentication: `Authorization: Bearer <DARTMOUTH_API_TOKEN>` on every `/v1` route; missing or invalid credentials return 401. Health is public. The scaffold returns 501 for planned routes and does not implement authentication yet. Keep it bound to loopback. A hosted backend must add TLS, token verification, request size limits, and durable storage before use.

## Lifecycle

`pending` → `approved` or `rejected` after grading. Each proposal represents one immutable code revision. Changed code creates a new proposal. Approval covers only its exact `commit_sha` and diff; it never grants permission to execute arbitrary code.

### GET /health

200: `{"status":"ok","api_version":"v1","implementation":"scaffold"}`

### POST /v1/proposals

Create a proposal and its fixed question set. Request:

```json
{"repository":"Rwohman2025/Dartmouth","commit_sha":"0123456789012345678901234567890123456789","diff":"diff --git a/example.js b/example.js\n...","summary":"Explain the proposed change"}
```

All fields are required, nonempty strings. `commit_sha` must be the full Git commit ID. `repository` is owner/name; `diff` is a unified diff. Do not send credentials, private keys, or unrelated source files.

201 response:

```json
{"proposal_id":"prop_example","repository":"Rwohman2025/Dartmouth","commit_sha":"0123456789012345678901234567890123456789","status":"pending","created_at":"2026-10-30T12:00:00Z"}
```

### GET /v1/proposals/{proposal_id}/questions

200 response:

```json
{"proposal_id":"prop_example","questions":[{"question_id":"q_1","prompt":"What boundary case does this change affect?"}]}
```

Questions remain stable for a proposal. An empty question set cannot be graded as approved.

### POST /v1/proposals/{proposal_id}/grade

Request:

```json
{"answers":[{"question_id":"q_1","answer":"Describe the boundary case and the validation evidence."}]}
```

Exactly one nonempty answer per issued question is required; missing, duplicate, or unknown question IDs return 422. The backend owns grading and the approval threshold. Initial intended policy: approve only if every answer passes its rubric. Do not treat a client-supplied score as authoritative. Rubrics and model integration remain implementation work.

200 response:

```json
{"proposal_id":"prop_example","status":"approved","results":[{"question_id":"q_1","passed":true,"feedback":"Explains the boundary case and evidence."}],"graded_at":"2026-10-30T12:05:00Z"}
```

A rejected grade uses `status: "rejected"` and at least one failed result. Grading is terminal: repeat submissions return 409. Concurrent submissions must produce at most one grade event atomically.

### GET /v1/proposals/{proposal_id}

200: creation response fields plus `questions`, and `grade` (null while pending; otherwise the grading response). Never include auth tokens or internal rubric secrets.

### GET /v1/proposals/{proposal_id}/log

200 response:

```json
{"proposal_id":"prop_example","events":[{"sequence":1,"type":"proposal.created","at":"2026-10-30T12:00:00Z","data":{"status":"pending"}}]}
```

Append-only events, ordered by increasing sequence per proposal. Initial event types: `proposal.created`, `proposal.graded`. A grade event records status and question results. Persist state and log together; backend owns storage. No deletion or mutation endpoint is defined in v1.

## Errors and client behavior

```json
{"error":{"code":"NOT_IMPLEMENTED","message":"This endpoint is scaffolded only."}}
```

Codes: 400 `INVALID_JSON`, 401 `UNAUTHORIZED`, 404 `NOT_FOUND`, 409 `INVALID_STATE`, 422 `VALIDATION_ERROR`, 500 `INTERNAL_ERROR`, 501 `NOT_IMPLEMENTED`. Do not expose stack traces or secrets. Clients use a 10-second timeout and fail closed on errors, malformed responses, pending status, or mismatched revision. Do not automatically retry proposal creation or grading until idempotency is designed; GET requests may be retried.

## MCP mapping (Person A)

Planned local stdio MCP tools:

| Tool | Arguments | Backend operation |
| --- | --- | --- |
| `create_proposal` | repository, commit_sha, diff, summary | POST proposals |
| `get_questions` | proposal_id | GET questions |
| `submit_answers` | proposal_id, answers | POST grade |
| `get_proposal` | proposal_id | GET proposal |
| `get_proposal_log` | proposal_id | GET log |

Tool results carry the backend JSON payload. Transport/API errors must be MCP tool errors, never fabricated approvals. MCP initialization and tool schemas are not implemented in this scaffold.

## GitHub Action mapping (Person B)

Inputs: `backend-url` (required HTTPS URL for hosted use), `proposal-id` (required), `commit-sha` (required full revision). Token arrives through `DARTMOUTH_API_TOKEN` from a secret. Planned behavior: GET proposal, check exact revision, require approved status, then set output `approved` to `true`; all other outcomes fail the step. No grading, code execution, or PR comments are performed by this Action. Until implemented, the Action always fails explicitly.
