# Verification report

This document records what has been verified, how to reproduce each check, and what still needs real people. Raw outputs are in [`evidence/`](evidence/) and [`../experiments/results/`](../experiments/results/).

Environment: Windows 11, Python 3.12.14, Node 26.13.0, Docker 29.6.2 (Compose 5.3.1), Google Chrome 157 (headless, Playwright). Remote checks run on GitHub Actions (Ubuntu, Python 3.12, Node 24).

## Summary

| Area | Result | How to reproduce |
|---|---|---|
| Regression suite | **62 / 62 pass** from a fresh clone installed from `requirements-dev.lock` | `python -m pytest` |
| End-to-end release checks | **18 / 18 pass** against a live API server | `python scripts/verify_release.py` |
| Browser checks (375 / 768 / 1440 px) | **29 / 29 pass** against the Docker deployment | `python scripts/browser_check.py` |
| Docker Compose deployment | **All checks pass** (see below) | `docker compose up --build` |
| Experiments | **Reproduced exactly** from a clean clone (120 fits, 40 stability values, 517 predictions; timings excluded) | `python experiments/run_benchmarks.py` |
| Continuous integration | Tests, end-to-end verification and frontend build run on every push | `.github/workflows/quality.yml` |

## End-to-end release checks (`scripts/verify_release.py`)

These run in an isolated temporary data folder and database, against a real `uvicorn` server.

- A fresh server starts with no published run.
- The default analysis yields 517 reviews, 360 candidates and 7 themes. Provider provenance is `Rule-based: 7` when external transfer is not enabled.
- A second analysis (LSA) completes. Run history lists both runs, and the historical snapshot of the first run is unchanged.
- The evidence export downloads as an attachment and contains all 517 retained reviews.
- A review event is recorded, and a stale resubmission is rejected with **HTTP 409**.
- An invalid cluster count (**422**) and a path escape (**400**) are rejected, and the published run is unchanged.
- An untrusted browser origin cannot trigger an analysis (**403**).
- After a server restart, the published run and the review history persist.
- Failures injected at all six pipeline checkpoints (after ingestion, sentiment, clustering and insights, during publication, and before commit) leave the published results byte-for-byte unchanged.

## Browser checks (`scripts/browser_check.py`)

These ran against the production build served by Docker (nginx proxy at `/api`).

- **Overview:** shows analysed totals, cleaning counts (603 raw, 84 duplicates), score semantics ("not confidence") and the actual provider label.
- **Layout:** at 375, 768 and 1440 px there is no horizontal overflow and all three navigation labels are readable.
- **Keyboard:** Tab and Enter switch views, and the focus outline is visible (`solid`).
- **Rerun:** rerunning with K = 5 publishes a new run, refreshes the theme list to five themes, and keeps the selected detail inside the new run. Review requests are pinned to the new run ID, so no stale data appears.
- **History:** selecting a historical run switches every drill-down request to that run ID.
- **Evidence:** an action's evidence link opens the matching theme, with exact source text and row numbers.
- **Review form:** a demonstration review event is saved and shown. A concurrent change made through the API produces the message "This action was reviewed elsewhere. Refresh before submitting."
- **Export:** the exported bundle matches the displayed run ID and review count, and retains both the original advice and the review history.
- **API outage:** the UI shows an actionable error with a Retry button instead of an empty-data screen, and recovers after Retry.
- **Long text:** long NHTSA complaint text wraps at 375 px with no overflow and no clipped buttons.
- **Console:** no unexpected console errors.

Screenshots are in [`images/ui/`](images/ui/).

**Real outage test.** With the API container actually stopped, the proxy originally took about 39 s to fail (nginx's default connect timeout) and the UI showed a generic message. This was fixed with `proxy_connect_timeout 5s` and specific outage messages in the frontend. The proxy now returns 504 within 5 s, and the UI reports *"Cannot reach the DriveSense analysis service. Check that the API is running, then retry. (HTTP 504)"*. See [decision 003](decisions/003-outage-handling-and-release-verification.md).

## Docker Compose deployment

| Check | Observed |
|---|---|
| Image build from a clean clone | API and dashboard images built (about 2 min) |
| Healthchecks | `api=healthy`, `dashboard=healthy` |
| API not published on the host | `127.0.0.1:8000` refuses connections; only `127.0.0.1:5173` is exposed |
| Token handling | Direct in-network call to `api:8000/runs` without a token returns **401**; the nginx proxy injects the token server-side |
| Security headers | Content-Security-Policy, `nosniff` and `no-referrer` present |
| Analysis through the proxy | 517 reviews, 360 candidates, 7 themes |
| Read-only inputs | `touch /app/datasets/x` fails with *Read-only file system* |
| Writable state and non-root user | `drivesense_v2.db` owned by `appuser` (uid 10001) in the `analysis_state` volume |
| Export through the proxy | Attachment with 517 reviews, 7 themes, 7 insights |
| Restart persistence | Same published run ID after `docker compose restart` |

## Not yet verified (requires real people or credentials)

- **Independent annotation:** two annotators label the blank packs in [`../evaluation_data/`](../evaluation_data/), followed by adjudication. Until then, all accuracy figures use labels reconstructed from the synthetic data generator.
- **Expert assessment:** a qualified automotive or service reviewer rates the recommendations using `expert_review_blank.csv`.
- **Triage pilot:** paired manual and assisted triage times, using `triage_pilot_blank.csv`.
- **Live NVIDIA NIM run:** requires an API key. Success and failure paths are covered by mocked tests only.
- **Screen-reader and real-user usability:** automated checks cover keyboard access, focus, layout and errors, but not assistive-technology or user-satisfaction outcomes.
