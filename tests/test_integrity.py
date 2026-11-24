import subprocess
import sys
from pathlib import Path
import pytest
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from app.core import db
from app.core.pipeline import execute_pipeline
from app.core.locking import writer_lock
from app.core.config import BusyError
from app.core.views import snapshot

ROWS = [{"vehicle": "Test sedan", "review_text": "The brake pedal failed and I could not stop.", "rating": 1},
        {"vehicle": "Test EV", "review_text": "Great interior but the battery drains overnight.", "rating": 4}]


@pytest.mark.parametrize("stage", ["after_ingestion", "after_sentiment", "after_clustering", "after_insights", "during_publication", "before_commit"])
def test_fault_preserves_previous_publication(csv_file, stage):
    csv_file(ROWS)
    first = execute_pipeline()
    with db.get_session() as s:
        before = snapshot(s, export=True)
    def fail(where):
        if where == stage:
            raise RuntimeError("injected failure")
    with pytest.raises(RuntimeError):
        execute_pipeline(hook=fail)
    with db.get_session() as s:
        assert snapshot(s, export=True) == before
        assert db.published_id(s) == first["run_id"]
        assert list(s.scalars(select(db.AnalysisRun.status).order_by(db.AnalysisRun.started_at))) == ["succeeded", "failed"]
        assert s.scalar(select(func.count()).select_from(db.Review)) == len(ROWS)


def test_custom_then_default_reloads_correct_source(csv_file):
    default = csv_file(ROWS)
    custom = csv_file([{"vehicle": "CUSTOM_ONLY", "review_text": "The screen freezes.", "rating": 2}], "custom.csv")
    a = execute_pipeline(custom)
    b = execute_pipeline()
    assert a["source_sha256"] != b["source_sha256"]
    assert b["reviews_scored"] == 2 and b["data_reused"] is False
    with db.get_session() as s:
        assert len(snapshot(s, a["run_id"], True)["reviews"]) == 1
        assert snapshot(s)["run"]["id"] == b["run_id"]


def test_thread_and_process_writers_are_rejected(isolated):
    with writer_lock(db.DB_PATH):
        with pytest.raises(BusyError):
            with writer_lock(db.DB_PATH):
                pass
        code = "from app.core.locking import writer_lock; import sys;\nwith writer_lock(sys.argv[1]): print('acquired')"
        child = subprocess.run([sys.executable, "-c", code, db.DB_PATH], capture_output=True, text=True, timeout=30)
        assert child.returncode != 0 and "BusyError" in child.stderr
    with writer_lock(db.DB_PATH):
        pass


def test_constraints_block_cross_run_and_duplicate_insight(csv_file):
    csv_file(ROWS)
    first, second = execute_pipeline(), execute_pipeline()
    with db.get_session() as s:
        old = s.scalar(select(db.Theme).where(db.Theme.run_id == first["run_id"]))
        action = s.scalar(select(db.Insight).where(db.Insight.run_id == second["run_id"]))
        assert s.execute(__import__('sqlalchemy').text("PRAGMA foreign_keys")).scalar() == 1
        values = {k: getattr(action, k) for k in ("run_id", "theme_id", "severity", "main_issue", "engineering_recommendation", "service_recommendation", "provider", "rule_id")}
    with pytest.raises(IntegrityError), db.get_session() as s, s.begin():
        s.add(db.Insight(**values)); s.flush()
    with pytest.raises(IntegrityError), db.get_session() as s, s.begin():
        s.add(db.Review(run_id=second["run_id"], theme_id=old.id, source_row=999, vehicle="X", review_text="broken",
            rating=1, sentiment="negative", sentiment_score=-0.5, complaint_candidate=True, routing_evidence=[]));s.flush()


def test_abandoned_run_is_recorded_as_interrupted(csv_file):
    csv_file(ROWS)
    with db.get_session() as s, s.begin():
        s.add(db.AnalysisRun(id="abandoned", status="running", source_name="x.csv", source_sha256="a"*64, config={}))
    execute_pipeline()
    with db.get_session() as s:
        assert s.get(db.AnalysisRun, "abandoned").status == "interrupted"
