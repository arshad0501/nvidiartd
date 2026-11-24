# Demonstration guide (about 8 minutes)

## Before the demo

```bash
python run_pipeline.py                                              # creates the published run
python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000     # terminal 1
cd frontend && npm run dev                                          # terminal 2, then open http://127.0.0.1:5173
```

Docker alternative: `docker compose up --build`, then open http://127.0.0.1:5173.

Keep http://127.0.0.1:8000/docs open in a second tab for the API steps. (With Docker the API is private, so use the workspace instead.)

## Script

1. **Problem (30 s).** Owner reviews contain early quality signals, but star ratings and sentiment counts do not say *what* is wrong or *who* should act.
2. **Overview (1 min).** Point to 603 raw → 517 clean rows, the 259 / 89 / 169 sentiment split, and **360 complaint candidates**. Explain that 101 of these reached analysis only through complaint cues (factual complaints with neutral or positive tone). Note the provenance banner: *7 Rule-based actions*, and VADER compound is polarity intensity, not confidence.
3. **Theme evidence (1.5 min).** Open *Brake System Issues* (35 reviews). Show the keywords, a source review with its row number and VADER score, and the routing span that explains why it was selected.
4. **Action review (1.5 min).** Show the severity-sorted cards. Expand *Selected source evidence*, then *Open theme evidence* to show the traceability round trip. Record a review clearly labelled as a demonstration, and show the review history.
5. **Rerun and history (1 min).** Change *Requested clusters* to 5 and run the analysis. Every view refreshes to the new run. Select the earlier run from the history list to show that it is preserved unchanged.
6. **Export (30 s).** Click *Export evidence bundle*. The JSON contains the run ID, input SHA-256, parameters, every review, the original advice and the review history.
7. **Reliability (1 min).** Explain atomic publication: `scripts/verify_release.py` injects failures at six checkpoints, and the published run never changes. Optionally stop the API and show the outage message and Retry.
8. **Results and limits (1 min).** Routing recall on the synthetic diagnostic rose from 71.0 % to 97.6 %; 62 tests pass; Docker, browser and CI checks are in `docs/VERIFICATION.md`. State the limits clearly: synthetic data with reconstructed labels, no expert validation yet, and NIM covered by mocked tests only.

## Optional: NVIDIA NIM

Set `NVIDIA_API_KEY` **and** `DRIVESENSE_ALLOW_EXTERNAL=1` before starting the API. Each action card then shows its actual provider (`NVIDIA NIM / meta/llama-3.1-70b-instruct`), or the fallback reason if validation fails.
