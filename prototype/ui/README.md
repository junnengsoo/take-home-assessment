# UI direction prototype

> Throwaway prototype — not production implementation.

This prototype asks: **which information hierarchy best helps Attorneys work
their assigned queue while retaining awareness of the shared queue, while also
giving Prospects a calm and trustworthy submission experience?**

Run from the repository root:

```sh
pnpm prototype
```

Then open <http://127.0.0.1:4173/>. Use the floating controls or the left/right
arrow keys to compare:

- **A — Guided calm:** reassuring single-page intake and table-first operations
- **B — Focused workflow:** staged intake and inbox-style review
- **C — Operational clarity:** compact intake and queue-summary workspace

The Public Intake, Attorney Workspace, and Lead Detail surfaces are selectable
inside every variant. All data and mutations are mocked.

