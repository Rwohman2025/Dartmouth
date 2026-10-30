# Dartmouth

Monorepo for a local MCP gate backed by questions, grading, and an auditable proposal log.
This is an initial scaffold, not a completed review or security gate.

| Path | Owner | Responsibility |
| --- | --- | --- |
| `mcp-gate/` | Person A | Local MCP server and backend client |
| `backend/` | Person B | Questions, grading, proposal log |
| `action/` | Person B | GitHub Action integration |
| `demo/` | Shared | Deliberately buggy demonstration inputs |

Start with [CONTRACT.md](CONTRACT.md). Agent guidance lives in [CLAUDE.md](CLAUDE.md) and [AGENTS.md](AGENTS.md).

## Local development

Prerequisite: Node.js 22 or newer. No external packages are required for the scaffold.

```sh
node --test backend/test/*.test.mjs
node backend/src/server.mjs
# In another terminal:
curl http://127.0.0.1:8000/health
```

The backend exposes health and returns explicit `501 NOT_IMPLEMENTED` responses for planned API routes. The MCP executable exits with an implementation message. The Action validates its configuration then fails explicitly until its backend integration is implemented; it never reports a placeholder approval.

## First implementation milestones

1. Agree on and evolve CONTRACT.md together.
2. Person B implements proposal storage, question generation, and grading behind the versioned API.
3. Person A implements MCP transport, tool schemas, and the backend client.
4. Person B wires the Action to the same API and adds end-to-end checks.

Keep credentials out of commits. Copy `.env.example` into your local environment as needed; no code currently loads dotenv files automatically.
