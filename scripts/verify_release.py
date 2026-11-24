"""End-to-end release verification against a live API server.

Runs in an isolated temporary data directory and database, so the user's
data/ folder and database are never modified. It exercises:

  1. a fresh server start and health check,
  2. a default analysis and a second (LSA) analysis,
  3. run history, historical snapshots and evidence export,
  4. a human-review event and a stale-version conflict (HTTP 409),
  5. invalid input rejected without changing the published run,
  6. injected failures at every pipeline checkpoint (published run unchanged),
  7. a server restart (published run and review history persist),
  8. local-mode access boundary (untrusted browser origin rejected).

Usage:  python scripts/verify_release.py [--out docs/evidence/release_verification.json]
"""
import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CHECKPOINTS = ["after_ingestion", "after_sentiment", "after_clustering", "after_insights",
               "during_publication", "before_commit"]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(env, port):
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.api.main:app", "--host", "127.0.0.1",
                             "--port", str(port), "--log-level", "warning"], cwd=ROOT, env=env)
    base = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            if requests.get(base + "/health", timeout=1).status_code == 200:
                return proc, base
        except requests.RequestException:
            pass
        time.sleep(0.25)
    proc.kill()
    raise RuntimeError("API server did not become healthy")


def stop_server(proc):
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "docs" / "evidence" / "release_verification.json"))
    args = parser.parse_args()
    checks, facts = [], {}

    def check(name, ok, detail=""):
        checks.append({"check": name, "passed": bool(ok), "detail": detail})
        print(("PASS " if ok else "FAIL ") + name + (f" - {detail}" if detail else ""))

    work = Path(tempfile.mkdtemp(prefix="drivesense_verify_"))
    data_dir, db_path = work / "data", work / "state" / "verify.db"
    data_dir.mkdir(); db_path.parent.mkdir()
    for name in ("reviews_raw.csv", "nhtsa_public_sample.csv"):
        shutil.copy(ROOT / "data" / name, data_dir / name)
    env = {**os.environ, "DRIVESENSE_DATA_DIR": str(data_dir), "DRIVESENSE_DB_PATH": str(db_path),
           "DRIVESENSE_ACCESS_MODE": "local", "DRIVESENSE_ALLOW_EXTERNAL": "0"}
    env.pop("NVIDIA_API_KEY", None)
    port = free_port()
    try:
        # 1-2. fresh start and analyses
        proc, base = start_server(env, port)
        h = requests.get(base + "/health").json()
        check("fresh server starts with no published run", h["published_run_id"] is None)
        t0 = time.perf_counter()
        r1 = requests.post(base + "/analyze", json={}).json()
        facts["default_run_seconds_http"] = round(time.perf_counter() - t0, 3)
        check("default analysis completes", r1.get("status") == "complete",
              f"{r1.get('reviews_ingested')} reviews, {r1.get('themes_discovered')} themes")
        facts["default_run"] = {k: r1.get(k) for k in ("reviews_ingested", "themes_discovered", "insights_generated", "source_sha256")}
        facts["default_run"]["candidates"] = r1["metrics"]["candidate_count"]
        facts["default_run"]["sentiment_counts"] = r1["metrics"]["sentiment_counts"]
        check("default run matches documented release values",
              (r1["reviews_ingested"], r1["metrics"]["candidate_count"], r1["themes_discovered"]) == (517, 360, 7))
        snap1 = requests.get(base + "/dashboard/snapshot").json()
        facts["default_themes"] = [(t["theme_name"], t["review_count"]) for t in snap1["themes"]]
        facts["severity"] = snap1["summary"]["severity_breakdown"]
        facts["providers"] = snap1["run"]["metrics"]["provider_counts"]
        check("provider provenance is truthful without NIM consent", facts["providers"] == {"Rule-based": 7})
        r2 = requests.post(base + "/analyze", json={"backend": "lsa"}).json()
        check("second analysis (LSA) completes", r2.get("status") == "complete")

        # 3. history, historical snapshot, export
        runs = requests.get(base + "/runs").json()
        check("run history lists both runs", len([r for r in runs if r["status"] == "succeeded"]) == 2)
        hist = requests.get(base + "/dashboard/snapshot", params={"run_id": r1["run_id"]}).json()
        check("historical snapshot returns the first run unchanged", digest(hist["themes"]) == digest(snap1["themes"]))
        exp = requests.get(f"{base}/runs/{r1['run_id']}/export")
        bundle = exp.json()
        check("evidence export downloads as attachment", "attachment" in exp.headers.get("content-disposition", ""))
        check("export contains every retained review", len(bundle.get("reviews", [])) == 517,
              f"{len(bundle.get('reviews', []))} reviews")

        # 4. human review + conflict
        latest = requests.get(base + "/dashboard/snapshot").json()
        action = latest["insights"][0]
        review = {"expected_version": action["review_version"], "decision": "accepted",
                  "reviewer": "Verification script", "note": "Automated release check of the review workflow."}
        ok = requests.post(f"{base}/insights/{action['id']}/review", json=review)
        check("review event recorded", ok.status_code == 200 and ok.json()["version"] == 1)
        stale = requests.post(f"{base}/insights/{action['id']}/review", json=review)
        check("stale review rejected with 409 conflict", stale.status_code == 409)
        published_before = requests.get(base + "/health").json()["published_run_id"]

        # 5. invalid input
        bad = requests.post(base + "/analyze", json={"n_clusters": 0})
        check("invalid cluster count rejected (422)", bad.status_code == 422)
        escape = requests.post(base + "/analyze", json={"csv_path": "../../secret.csv"})
        check("path escape rejected (400)", escape.status_code == 400)
        check("published run unchanged after rejected input",
              requests.get(base + "/health").json()["published_run_id"] == published_before)

        # 8. access boundary
        foreign = requests.post(base + "/analyze", json={}, headers={"Origin": "https://evil.example"})
        check("untrusted browser origin cannot mutate (403)", foreign.status_code == 403)

        # 7. restart persistence
        snap_before_restart = requests.get(base + "/dashboard/snapshot").json()
        stop_server(proc)
        proc, base = start_server(env, port)
        snap_after = requests.get(base + "/dashboard/snapshot").json()
        check("published run persists across restart", snap_after["run"]["id"] == snap_before_restart["run"]["id"])
        reviewed = [a for a in snap_after["insights"] if a["id"] == action["id"]][0]
        check("review history persists across restart", len(reviewed["review_history"]) == 1)
        stop_server(proc)

        # 6. injected failures (in-process, same database)
        os.environ.update({k: v for k, v in env.items() if k.startswith("DRIVESENSE_")})
        from app.core import db
        from app.core.pipeline import execute_pipeline
        from app.core.views import snapshot
        db.configure_database(db_path); db.init_db()
        with db.get_session() as s:
            reference = digest(snapshot(s))
        survived = []
        for stage in CHECKPOINTS:
            def fail(current, stage=stage):
                if current == stage:
                    raise RuntimeError("injected failure at " + stage)
            try:
                execute_pipeline(hook=fail)
            except RuntimeError:
                pass
            with db.get_session() as s:
                survived.append(digest(snapshot(s)) == reference)
        check("published results unchanged after failures at all 6 checkpoints", all(survived),
              ", ".join(f"{c}:{'ok' if v else 'CHANGED'}" for c, v in zip(CHECKPOINTS, survived)))
        db.engine.dispose()
    finally:
        try:
            stop_server(proc)
        except Exception:
            pass
        shutil.rmtree(work, ignore_errors=True)

    result = {"generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "python": sys.version.split()[0], "passed": sum(c["passed"] for c in checks),
              "total": len(checks), "checks": checks, "facts": facts}
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\n{result['passed']}/{result['total']} checks passed -> {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    sys.exit(0 if result["passed"] == result["total"] else 1)


if __name__ == "__main__":
    main()
