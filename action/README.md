# GitHub Action — Person B

Local composite Action entrypoint: action.yml. It deliberately fails until backend verification is implemented. Do not use it as an operational merge gate yet.

Future usage after checkout (example only; no workflow is installed):

```yaml
- uses: ./action
  with:
    backend-url: https://your-backend.example
    proposal-id: prop_example
    commit-sha: ${{ github.sha }}
  env:
    DARTMOUTH_API_TOKEN: ${{ secrets.DARTMOUTH_API_TOKEN }}
```

Follow CONTRACT.md: GET proposal, require approved status and exact commit match, set approved output only on verified success. Use the revision actually being gated (PR head and merge commits differ). Hosted runners cannot access your laptop's localhost. Never expose tokens to untrusted fork code or use pull_request_target to run untrusted code with secrets. Start with read-only repository permissions; no write access is needed for verification.
