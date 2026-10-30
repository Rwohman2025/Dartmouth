# Claude Code guidance

Read README.md, CONTRACT.md, and AGENTS.md first. Follow the same ownership, security, validation, and preservation rules as Codex.

Person A implements the local MCP server in mcp-gate/. Person B implements backend questions, grading, proposal logging, and the action/. CONTRACT.md is the shared API source of truth.

This repository starts as a scaffold. Do not claim MCP protocol support, production authentication, durable logging, or real grading until implemented and checked. Fail closed when backend status cannot be verified. Keep planted bugs in demo/ intact unless explicitly asked to repair them.
