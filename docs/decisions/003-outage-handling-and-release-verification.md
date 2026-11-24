# 003 — Outage handling and automated release verification

Status: accepted, 25 November 2026.

## Context

Live checks against the Docker deployment showed that when the API container was stopped, the nginx proxy waited for its default 60 s connect timeout (about 39 s observed) before returning an error. The workspace then showed the generic message "The service could not complete this request". Read requests also shared the 90 s timeout used for analysis runs. Browser, Docker and end-to-end checks had previously been manual checklist items that could not be reproduced.

## Decision

- **Fail fast:** nginx uses `proxy_connect_timeout 5s` for `/api/`. `proxy_read_timeout 120s` is unchanged, so long analyses still complete.
- **Shorter timeouts for reads:** the frontend uses a 20 s timeout for GET requests and keeps 90 s for POST (analysis).
- **Specific messages:** network failures and 502/503/504 responses produce *"Cannot reach the DriveSense analysis service. Check that the API is running, then retry."* with the HTTP status. Timeouts produce a separate message. API validation details are still shown verbatim.
- **Reproducible verification:**
  - `scripts/verify_release.py` runs the end-to-end server checks in an isolated temporary database, and CI runs it on every push.
  - `scripts/browser_check.py` drives a real Chrome against any deployment at three widths.
  - Results are written to `docs/evidence/`.

## Consequences

- A real outage is reported within about 6 s, with an actionable message and a working Retry button.
- The browser checks need Playwright, which is deliberately kept out of the runtime lockfile. The checks record demonstration review events, so they must be pointed at a disposable deployment.
- Automated checks do not replace screen-reader testing or real-user studies; see `docs/VERIFICATION.md`.
