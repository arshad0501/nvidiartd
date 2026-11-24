"""Run-scoped read models; snapshot/export use one database read transaction."""
from sqlalchemy import select, func
from app.core import db


def run_dict(run):
    return {key: getattr(run, key) for key in ("id", "status", "started_at", "completed_at", "source_name",
            "source_sha256", "config", "cleaning", "metrics", "error_code")}


def review_dict(review):
    return {key: getattr(review, key) for key in ("id", "run_id", "source_row", "vehicle", "review_text", "rating",
            "sentiment", "sentiment_score", "complaint_candidate", "routing_evidence", "theme_id")}


def event_dict(row):
    return {key: getattr(row, key) for key in ("id", "version", "decision", "reviewer", "note", "edits", "created_at")}


def selected_run(session, run_id=None):
    identity = run_id or db.published_id(session)
    run = session.get(db.AnalysisRun, identity) if identity else None
    if run_id and (run is None or run.status != "succeeded"):
        raise LookupError("Successful analysis run not found.")
    return run


def snapshot(session, run_id=None, export=False):
    run = selected_run(session, run_id)
    if run is None:
        return {"run": None, "summary": None, "themes": [], "insights": []}
    rid = run.id
    themes = list(session.scalars(select(db.Theme).where(db.Theme.run_id == rid).order_by(db.Theme.id)))
    actions = list(session.scalars(select(db.Insight).where(db.Insight.run_id == rid).order_by(db.Insight.id)))
    evidence = list(session.execute(select(db.Evidence, db.Review).join(db.Review,
        db.Evidence.review_id == db.Review.id).where(db.Evidence.run_id == rid).order_by(db.Evidence.id)))
    events = list(session.scalars(select(db.ReviewEvent).where(db.ReviewEvent.run_id == rid).order_by(db.ReviewEvent.version)))
    grouped = {}
    for link, review in evidence:
        grouped.setdefault(link.insight_id, []).append({**review_dict(review), "selection": link.selection})
    history = {}
    for e in events:
        history.setdefault(e.insight_id, []).append(event_dict(e))
    names = {t.id: t.theme_name for t in themes}
    action_rows = []
    for a in actions:
        result = {key: getattr(a, key) for key in ("id", "run_id", "theme_id", "severity", "main_issue",
            "engineering_recommendation", "service_recommendation", "provider", "model", "fallback_reason", "rule_id", "review_version")}
        result.update(theme_name=names[a.theme_id], evidence=grouped.get(a.id, []),
            review_history=history.get(a.id, []), advisory=True)
        action_rows.append(result)
    sentiment_counts = dict(session.execute(select(db.Review.sentiment, func.count()).where(db.Review.run_id == rid).group_by(db.Review.sentiment)).all())
    total = sum(sentiment_counts.values())
    candidate_count = session.scalar(select(func.count()).select_from(db.Review).where(db.Review.run_id == rid, db.Review.complaint_candidate.is_(True)))
    theme_rows = [{key: getattr(t, key) for key in ("id", "run_id", "theme_name", "review_count", "keywords", "explanation")} for t in themes]
    summary = {"run_id": rid, "total_reviews": total, "positive_reviews": sentiment_counts.get("positive", 0),
        "negative_reviews": sentiment_counts.get("negative", 0), "neutral_reviews": sentiment_counts.get("neutral", 0),
        "positive_rate": round(sentiment_counts.get("positive", 0)/total, 4) if total else 0,
        "complaint_candidates": candidate_count, "theme_count": len(themes),
        "themes_by_size": sorted(theme_rows, key=lambda x: -x["review_count"]),
        "severity_breakdown": {level: sum(a.severity == level for a in actions) for level in ("Critical", "High", "Medium", "Low")}}
    result = {"run": run_dict(run), "summary": summary, "themes": theme_rows, "insights": action_rows,
        "limitations": ["Synthetic demonstration data unless a different documented source is selected.",
                         "Polarity scores are not confidence probabilities.",
                         "Complaint routing and component labels can be wrong; human review required.",
                         "Severity is an advisory rule/model assessment, not a verified safety diagnosis."]}
    if export:
        result["reviews"] = [review_dict(r) for r in session.scalars(select(db.Review).where(db.Review.run_id == rid).order_by(db.Review.id))]
    return result
