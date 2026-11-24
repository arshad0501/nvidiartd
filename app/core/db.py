"""Versioned SQLite storage. Original drivesense.db is never modified."""
import os
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import (create_engine, event, Column, Integer, String, Float, Text,
                        Boolean, JSON, ForeignKey, ForeignKeyConstraint,
                        UniqueConstraint, CheckConstraint)
from sqlalchemy.orm import declarative_base, sessionmaker
from app.core.config import DATA_DIR

Base = declarative_base()
DB_PATH = str(Path(os.environ.get("DRIVESENSE_DB_PATH", DATA_DIR / "drivesense_v2.db")).resolve())
engine = None
SessionLocal = sessionmaker(expire_on_commit=False)


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    id = Column(String(36), primary_key=True)
    status = Column(String(16), nullable=False)
    started_at = Column(String(40), nullable=False, default=utcnow)
    completed_at = Column(String(40))
    source_name = Column(String(256), nullable=False)
    source_sha256 = Column(String(64), nullable=False)
    config = Column(JSON, nullable=False)
    cleaning = Column(JSON, nullable=False, default=dict)
    metrics = Column(JSON, nullable=False, default=dict)
    error_code = Column(String(64))
    __table_args__ = (CheckConstraint("status IN ('running','succeeded','failed','interrupted')"),)


class PublishedRun(Base):
    __tablename__ = "published_run"
    id = Column(Integer, primary_key=True)
    run_id = Column(String(36), ForeignKey("analysis_runs.id"), nullable=False)
    __table_args__ = (CheckConstraint("id = 1"),)


class Theme(Base):
    __tablename__ = "themes"
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), ForeignKey("analysis_runs.id"), nullable=False, index=True)
    theme_name = Column(String(256), nullable=False)
    review_count = Column(Integer, nullable=False)
    keywords = Column(Text, nullable=False)
    explanation = Column(JSON, nullable=False, default=dict)
    __table_args__ = (UniqueConstraint("run_id", "id"), CheckConstraint("review_count > 0"))


class Review(Base):
    __tablename__ = "reviews"
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), ForeignKey("analysis_runs.id"), nullable=False, index=True)
    source_row = Column(Integer, nullable=False)
    vehicle = Column(String(128), nullable=False)
    review_text = Column(Text, nullable=False)
    rating = Column(Integer, nullable=True)
    sentiment = Column(String(16), nullable=False)
    sentiment_score = Column(Float, nullable=False)
    complaint_candidate = Column(Boolean, nullable=False)
    routing_evidence = Column(JSON, nullable=False)
    theme_id = Column(Integer, nullable=True, index=True)
    __table_args__ = (
        UniqueConstraint("run_id", "id"), UniqueConstraint("run_id", "source_row"),
        ForeignKeyConstraint(["run_id", "theme_id"], ["themes.run_id", "themes.id"]),
        CheckConstraint("rating IS NULL OR rating BETWEEN 1 AND 5"),
        CheckConstraint("sentiment IN ('positive','neutral','negative')"),
        CheckConstraint("sentiment_score BETWEEN -1 AND 1"),
    )


class Insight(Base):
    __tablename__ = "insights"
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), ForeignKey("analysis_runs.id"), nullable=False, index=True)
    theme_id = Column(Integer, nullable=False, unique=True)
    severity = Column(String(16), nullable=False)
    main_issue = Column(Text, nullable=False)
    engineering_recommendation = Column(Text, nullable=False)
    service_recommendation = Column(Text, nullable=False)
    provider = Column(String(64), nullable=False)
    model = Column(String(128))
    fallback_reason = Column(String(64))
    rule_id = Column(String(128), nullable=False)
    review_version = Column(Integer, nullable=False, default=0)
    __table_args__ = (
        UniqueConstraint("run_id", "id"),
        ForeignKeyConstraint(["run_id", "theme_id"], ["themes.run_id", "themes.id"]),
        CheckConstraint("severity IN ('Low','Medium','High','Critical')"),
    )


class Evidence(Base):
    __tablename__ = "action_evidence"
    id = Column(Integer, primary_key=True)
    run_id = Column(String(36), nullable=False)
    insight_id = Column(Integer, nullable=False, index=True)
    review_id = Column(Integer, nullable=False)
    selection = Column(String(64), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(["run_id", "insight_id"], ["insights.run_id", "insights.id"]),
        ForeignKeyConstraint(["run_id", "review_id"], ["reviews.run_id", "reviews.id"]),
        UniqueConstraint("insight_id", "review_id"),
    )


class ReviewEvent(Base):
    __tablename__ = "review_events"
    id = Column(Integer, primary_key=True)
    run_id = Column(String(36), nullable=False)
    insight_id = Column(Integer, nullable=False, index=True)
    version = Column(Integer, nullable=False)
    decision = Column(String(16), nullable=False)
    reviewer = Column(String(80), nullable=False)
    note = Column(Text, nullable=False)
    edits = Column(JSON, nullable=False, default=dict)
    created_at = Column(String(40), nullable=False, default=utcnow)
    __table_args__ = (
        ForeignKeyConstraint(["run_id", "insight_id"], ["insights.run_id", "insights.id"]),
        UniqueConstraint("insight_id", "version"),
        CheckConstraint("decision IN ('accepted','edited','rejected')"),
    )


def configure_database(path=None):
    global engine, DB_PATH
    if engine is not None:
        engine.dispose()
    if path is not None:
        DB_PATH = str(Path(path).resolve())
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{Path(DB_PATH).as_posix()}",
                           connect_args={"check_same_thread": False, "timeout": 15})

    @event.listens_for(engine, "connect")
    def sqlite_constraints(connection, _):
        connection.isolation_level = None
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.close()

    @event.listens_for(engine, "begin")
    def explicit_begin(connection):
        # Ensure a multi-query read sees one SQLite snapshot, including on the
        # stdlib driver's legacy transaction mode.
        connection.exec_driver_sql("BEGIN")

    SessionLocal.configure(bind=engine)
    return engine


def init_db():
    if engine is None:
        configure_database()
    Base.metadata.create_all(engine)


def get_session():
    return SessionLocal()


def published_id(session):
    row = session.get(PublishedRun, 1)
    return row.run_id if row else None
