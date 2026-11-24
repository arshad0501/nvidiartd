# Data provenance

reviews_raw.csv is the original supplied synthetic dataset. It contains handwritten automotive templates, fictional vehicle names and random lead-ins, with injected dirty rows. Do not call it real owner feedback. The generator can reproduce a separate CSV using seed 42. Ratings encode intended generator sentiment and are not independent ground truth.

The application creates data/drivesense_v2.db on first run. It is ignored by Git and stores immutable, versioned run outputs plus separately versioned human review events.

nhtsa_public_sample.csv contains a bounded sample from the official public NHTSA complaint endpoint. The matching provenance JSON records URL, time, SHA-256 digests, public ODI record IDs, selection and preprocessing. The importer retains summary text only and leaves ratings unknown. Common VIN/email/phone patterns are redacted; residual personal information may remain, so manually review before redistribution or hosted inference.

NHTSA owner reports are unverified allegations, not confirmed defects. This complaint-selected sample has no real noncomplaint controls, and no independent sentiment/theme/severity labels. Use it to demonstrate input compatibility; do not report candidate counts as classification accuracy or claim representative defect prevalence. See https://www.nhtsa.gov/nhtsa-datasets-and-apis for source context.

Changing any CSV changes the next run's input digest; old outputs retain their original hash. Source-row identifiers refer to logical CSV records, not physical lines containing multiline quoted narratives.
