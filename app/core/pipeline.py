"""Compute first, publish atomically; retain prior successful runs."""
import importlib.metadata
import time
import uuid
import pandas as pd
from sqlalchemy import select
from app.core import db
from app.core.config import InputError, PIPELINE_VERSION, resolve_csv
from app.core.ingestion import load_reviews, clean_reviews
from app.core.sentiment import score_text
from app.core.complaints import complaint_evidence
from app.core.clustering import discover_themes
from app.core.insights import generate_insights
from app.core.locking import writer_lock


def execute_pipeline(csv_path=None, n_clusters=7, routing="complaint_aware", backend="tfidf", hook=None):
    if type(n_clusters) is not int or not 1 <= n_clusters <= 30:
        raise InputError("Cluster count must be an integer from 1 to 30.")
    if routing not in ("complaint_aware", "negative_only") or backend not in ("tfidf", "lsa"):
        raise InputError("Unsupported routing or embedding backend.")
    path = resolve_csv(csv_path)
    db.init_db()
    with writer_lock(db.DB_PATH):
        start = time.perf_counter()
        raw = load_reviews(path)
        frame = clean_reviews(raw)
        if frame.empty:
            raise InputError("No usable review rows remain after validation. Previous results were preserved.")
        versions = {p: importlib.metadata.version(p) for p in ["pandas", "scikit-learn", "vaderSentiment", "sqlalchemy", "numpy"]}
        config = {"pipeline_version": PIPELINE_VERSION, "n_clusters": n_clusters, "routing": routing,
                  "embedding_backend": backend, "preprocessing": "discourse-v2", "random_seed": 42,
                  "n_init": 10, "versions": versions}
        run_id = str(uuid.uuid4())
        with db.get_session() as session, session.begin():
            for abandoned in session.scalars(select(db.AnalysisRun).where(db.AnalysisRun.status == "running")):
                abandoned.status = "interrupted"; abandoned.completed_at = db.utcnow(); abandoned.error_code = "process_interrupted"
            session.add(db.AnalysisRun(id=run_id, status="running", source_name=path.name,
                        source_sha256=raw.attrs["source_sha256"], config=config, cleaning=frame.attrs["cleaning"]))

        def checkpoint(stage):
            if hook:
                hook(stage)

        try:
            records = []
            checkpoint("after_ingestion")
            for row in frame.itertuples(index=False):
                label, compound = score_text(row.review_text)
                candidate, evidence = complaint_evidence(row.review_text, label, routing)
                records.append({"source_row": int(row.source_row), "vehicle": row.vehicle,
                    "review_text": row.review_text, "rating": None if pd.isna(row.rating) else int(row.rating),
                    "sentiment": label, "sentiment_score": compound,
                    "complaint_candidate": candidate, "routing_evidence": evidence})
            checkpoint("after_sentiment")
            themes, assignments, metrics = discover_themes(records, n_clusters, backend)
            checkpoint("after_clustering")
            advice = generate_insights(themes, records)
            checkpoint("after_insights")
            metrics.update({"review_count": len(records), "theme_count": len(themes),
                "insight_count": len(advice), "sentiment_counts": {label: sum(r["sentiment"] == label for r in records)
                    for label in ("positive", "neutral", "negative")},
                "provider_counts": {p: sum(a["provider"] == p for a in advice) for p in sorted({a["provider"] for a in advice})}})
            with db.get_session() as session, session.begin():
                theme_ids = {}
                for t in themes:
                    obj = db.Theme(run_id=run_id, theme_name=t["theme_name"], review_count=len(t["members"]),
                                   keywords=", ".join(t["keywords"]), explanation=t["explanation"])
                    session.add(obj); session.flush(); theme_ids[t["local_id"]] = obj.id
                review_ids = {}
                for i, record in enumerate(records):
                    obj = db.Review(run_id=run_id, **record, theme_id=theme_ids.get(assignments.get(i)))
                    session.add(obj); session.flush(); review_ids[record["source_row"]] = obj.id
                for action in advice:
                    fields = {k: action[k] for k in ("severity", "main_issue", "engineering_recommendation",
                              "service_recommendation", "provider", "model", "fallback_reason", "rule_id")}
                    obj = db.Insight(run_id=run_id, theme_id=theme_ids[action["theme_id"]], **fields)
                    session.add(obj); session.flush()
                    for source_row in action["evidence_ids"]:
                        session.add(db.Evidence(run_id=run_id, insight_id=obj.id, review_id=review_ids[source_row],
                                    selection="central/distinct/diverse"))
                checkpoint("during_publication")
                metrics["elapsed_seconds"] = round(time.perf_counter()-start, 6)
                run = session.get(db.AnalysisRun, run_id)
                run.status = "succeeded"; run.completed_at = db.utcnow(); run.metrics = metrics
                published = session.get(db.PublishedRun, 1)
                if published:
                    published.run_id = run_id
                else:
                    session.add(db.PublishedRun(id=1, run_id=run_id))
                checkpoint("before_commit")
            return {"status": "complete", "run_id": run_id, "reviews_ingested": len(records),
                "reviews_scored": len(records), "data_reused": False, "themes_discovered": len(themes),
                "insights_generated": len(advice), "source_sha256": raw.attrs["source_sha256"],
                "cleaning": frame.attrs["cleaning"], "metrics": metrics}
        except Exception as exc:
            with db.get_session() as session, session.begin():
                run = session.get(db.AnalysisRun, run_id)
                run.status = "failed"; run.completed_at = db.utcnow(); run.error_code = type(exc).__name__
            raise
