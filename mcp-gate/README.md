# Local MCP gate — Person A

Entry placeholder: `node mcp-gate/src/index.mjs` (intentionally exits with code 1).

Implement an MCP stdio server with a maintained SDK, schemas for the five tools in CONTRACT.md, and an HTTP backend client. Read DARTMOUTH_BACKEND_URL and DARTMOUTH_API_TOKEN from the environment. Send diagnostics to stderr so stdout remains available for MCP messages.

Acceptance: successful MCP initialization and tool discovery; tool/API mapping matches the contract; timeouts and backend errors become tool errors; no credentials in logs; approval always binds to the requested revision.
