# Set up a folder to use the gate

Follow these steps for any new folder. `<folder>` is the folder you want gated.

## 1. Make it a git repo with an `origin`

`propose_write` finds the repo root and the `owner/name` from git, so both are required.

```
cd <folder>
git init
git remote add origin https://github.com/<owner>/<name>.git
```

(With `MOCK_BACKEND=1` a missing `origin` is tolerated, but the folder must still be a git repo.)

## 2. Ignore the scratch folder

Add this line to `<folder>/.gitignore`:

```
.pending/
```

## 3. Register the MCP server: `<folder>/.mcp.json`

```json
{
  "mcpServers": {
    "mcp-gate": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "--directory",
        "C:\\Users\\iminl\\OneDrive\\Desktop\\Dartmouth\\Dartmouth\\mcp-gate",
        "run",
        "server.py"
      ],
      "env": {
        "MOCK_BACKEND": "1"
      }
    }
  }
}
```

- Testing without a backend: keep `"MOCK_BACKEND": "1"`.
- Real backend: remove it and set `BACKEND_URL` and `GATE_SECRET` in `env` instead.
  The server does not read `.env` on its own.

## 4. Lock down the built-in tools: `<folder>/.claude/settings.json`

```json
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "permissions": {
    "deny": ["Write", "Edit", "NotebookEdit"],
    "ask": ["Bash"]
  }
}
```

Deny rules beat ask rules, and ask rules beat allow rules, so a stray `allow` elsewhere
cannot undo this. Use bare tool names: path rules for `Write` and `NotebookEdit` never match.

## 5. Tell Claude: `<folder>/CLAUDE.md`

```markdown
All code must be saved with the `propose_write` tool (from the `mcp-gate` MCP server).

- To create or change any file, call `propose_write(file_path, content, task)`.
  Pass `file_path` as an absolute path and `content` as the complete new file.
- Do not use the Write, Edit or NotebookEdit tools. They are denied here.
- Do not write files through Bash (redirects, `tee`, `sed -i`, `cp`, scripts, etc.).
- If `propose_write` says the user has not shown understanding, stop. Do not
  retry it and do not write that file another way. Tell the user and let them decide.
```

## 6. Start and verify

```
cd <folder>
claude
```

1. Approve the project `mcp-gate` server when prompted.
2. Run `/mcp`: `mcp-gate` should show as connected.
3. Run `/status`: `Project settings` should be listed under `Setting sources`.
4. Ask Claude to create a small file. It should call `propose_write`, show you a form,
   and only write the file after you answer. With mock mode the file name must match a demo
   snippet (`average_scores.py`, `paginate_users.py`, `signup_age.py`).
5. Check that Write/Edit are blocked, and that every Bash command asks for permission.

## Known limit

This is a guardrail, not a sandbox. A Bash command you approve can still write files, so read
each Bash prompt before saying yes. Set `"deny": ["Bash"]` instead of `"ask"` if you want to
forbid it entirely.
