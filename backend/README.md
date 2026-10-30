# Backend — Person B

Run `node backend/src/server.mjs` from the repository root. Defaults to 127.0.0.1:8000; BACKEND_HOST and BACKEND_PORT override these values. Only health is functional. Planned /v1 routes return 501 and all other routes return 404.

Implementation boundaries:

- `src/questions/`: fixed per-proposal questions and internal rubrics.
- `src/grading/`: validate answer completeness and evaluate against rubrics.
- `src/proposals/`: immutable revision records, terminal state transitions, append-only events, and durable storage.

Use CONTRACT.md for payloads and acceptance rules. Before accepting real proposals, implement authentication, validation, limits, atomic persistence, and error handling. Keep local data under ignored backend/data/; choose a storage engine during implementation.
