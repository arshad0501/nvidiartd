# Browser verification still required

Automated browser access was unavailable and a native Chrome launch approval timed out. No live visual/interaction pass is claimed. API behavior and builds passed separately.

Use a disposable v2 run and inspect React at 375, 768 and 1440px:

- All three navigation labels remain readable; keyboard Tab/Enter and focus outlines work.
- Run the default CSV. Overview totals, cleaned/rejected counts, compound semantics and actual provider are readable.
- Select a theme, note its title/keywords/reviews. Rerun with a different K. All details refresh and no old review remains.
- Select a historical run. Every theme/review/action uses that run ID.
- Open an action's evidence, follow the theme link, and compare exact source text and rule spans.
- Submit a clearly labelled demonstration accept/edit/reject event; verify its history and retained original text in the export. Do not count this as expert validation.
- Repeat a stale version via API; verify 409 and useful UI refresh message.
- Stop the API temporarily; verify an error rather than a false empty-data screen. Restart and retry.
- Use an invalid K and a missing CSV via /docs; previous published output must remain unchanged.
- Export a JSON bundle; confirm its source digest/run ID/parameters and record counts match the screen.
- Check long NHTSA text wrapping and no horizontal overflow or clipped form buttons.

Record actual tester/date/browser/version, screenshots and failures. Do not pre-check these boxes based on source review.
