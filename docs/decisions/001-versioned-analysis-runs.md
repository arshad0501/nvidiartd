# Versioned analysis runs and publication

Status: accepted for implementation, 24 November 2026, following approval to implement all audit fixes.

The original pipeline deletes its database and commits stages independently. A failed or concurrent run can replace useful results with incomplete state. Timestamp-based reuse cannot identify the source dataset.

Use a separate `data/drivesense_v2.db` by default, preserving `data/drivesense.db` as the original snapshot. A configurable database path allows isolated tests. Analysis stages become pure transformations; a coordinator validates and computes the complete result, then writes all rows and the published-run pointer in one SQL transaction. A run journal records start, success or failure. Failed work never changes the published pointer. An OS file lock plus an in-process lock permits one mutating operation at a time across threads/processes. OS locks release on process death; abandoned run journal entries are marked interrupted on the next locked write.

Results are immutable except for separately recorded human review events. Every review, theme and insight belongs to a run, with composite foreign keys preventing cross-run associations. Reads can specify a historical run. The UI uses a single snapshot endpoint and pins drill-down requests to its run ID. No timestamp-based data cache is retained; each run hashes the exact bytes parsed. The existing API resource names remain, with additional metadata and run filters.

Trade-offs: historical data grows until an explicit retention policy is introduced; local SQLite and a synchronous bounded pipeline remain appropriate for this prototype. A task queue or PostgreSQL can be introduced if measured deployment requirements justify it. Database file replacement is avoided because open Windows SQLite connections make replacement fragile.

Acceptance: injected faults before/during publication preserve last successful output; a second writer is rejected; schema constraints reject orphans/cross-run links; original snapshot hash remains unchanged; fresh startup and historical reads work.
