# Instructions for Claude Code

We are building the Comprehension Gate: an MCP server that stops
AI-written code from being saved until the user answers questions about it.

- Read CONTRACT.md before writing anything that talks to the backend.
- Never edit CONTRACT.md. If it needs to change, stop and tell me why.
- Only create or edit files in mcp-gate/ and demo/ unless I say otherwise.
- Python 3.11+, uv for dependencies, FastMCP for the MCP server.
- Read secrets from environment variables or a .env file. Never hardcode them.
- I am new to this. After each task, explain in plain language what you
  built and give me the exact commands to test it.
- Keep each change small. Do not start the next task until I say so.