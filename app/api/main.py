"""Run-scoped FastAPI service for local automotive complaint triage."""
from contextlib import asynccontextmanager
import hmac
import ipaddress
import logging
import os
from typing import Literal
from uuid import UUID
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, text
from app.core import db
from app.core.config import InputError, BusyError
from app.core.pipeline import execute_pipeline
from app.core.insights import llm_status
from app.core.locking import writer_lock
from app.core.views import snapshot, run_dict, review_dict, selected_run, event_dict

logger = logging.getLogger(__name__)
LOCAL_ORIGINS = {f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (5173, 8501)}


@asynccontextmanager
async def lifespan(_):
    mode = os.environ.get("DRIVESENSE_ACCESS_MODE", "local")
    if mode not in ("local", "shared"):
        raise RuntimeError("DRIVESENSE_ACCESS_MODE must be local or shared")
    if mode == "shared" and len(os.environ.get("DRIVESENSE_API_TOKEN", "")) < 24:
        raise RuntimeError("Shared mode requires a random DRIVESENSE_API_TOKEN of at least 24 characters")
    db.init_db()
    yield


app = FastAPI(title="DriveSense AI", description="Evidence-linked automotive complaint triage; human review required.", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=sorted(LOCAL_ORIGINS),
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Authorization"])


@app.middleware("http")
async def access_boundary(request: Request, call_next):
    shared = os.environ.get("DRIVESENSE_ACCESS_MODE", "local") == "shared"
    if shared and request.url.path != "/health":
        expected = os.environ.get("DRIVESENSE_API_TOKEN", "")
        supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
        if not expected or not hmac.compare_digest(supplied, expected):
            return JSONResponse(status_code=401, content={"detail": "A valid access token is required."})
    elif not shared:
        try:
            local = request.client and ipaddress.ip_address(request.client.host).is_loopback
        except ValueError:
            local = False
        if not local:
            return JSONResponse(status_code=403, content={"detail": "Local mode accepts loopback clients only."})
    if request.method == "POST" and request.headers.get("origin") not in LOCAL_ORIGINS | {None}:
        return JSONResponse(status_code=403, content={"detail": "Mutation from this browser origin is not allowed."})
    return await call_next(request)


@app.exception_handler(InputError)
async def input_error(_, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(BusyError)
async def busy_error(_, exc):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(LookupError)
async def lookup_error(_, exc):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    csv_path: str | None = Field(default=None, max_length=512)
    n_clusters: int = Field(default=7, ge=1, le=30, strict=True)
    routing: Literal["complaint_aware", "negative_only"] = "complaint_aware"
    backend: Literal["tfidf", "lsa"] = "tfidf"
    refresh_data: bool = False  # Compatible field; v2 always hashes/recomputes input.


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_version: int = Field(ge=0, strict=True)
    decision: Literal["accepted", "edited", "rejected"]
    reviewer: str = Field(min_length=2, max_length=80)
    note: str = Field(min_length=8, max_length=2000)
    engineering_recommendation: str | None = Field(default=None, min_length=8, max_length=3000)
    service_recommendation: str | None = Field(default=None, min_length=8, max_length=3000)

    @model_validator(mode="after")
    def edits_consistent(self):
        edited = self.engineering_recommendation or self.service_recommendation
        if (self.decision == "edited") != bool(edited):
            raise ValueError("Edited decisions require replacement advice; other decisions must not contain edits.")
        return self


@app.get("/")
def root():
    return {"service": "DriveSense AI", "version": "2.0.0", "status": "ok", "documentation": "/docs"}


@app.get("/health")
def health():
    with db.get_session() as session:
        session.execute(text("SELECT 1"))
        current = db.published_id(session)
    return {"status": "ready", "published_run_id": current}


@app.get("/datasets")
def datasets():
    from app.core.config import DATA_DIR, MAX_CSV_BYTES
    return [{"name": p.name, "bytes": p.stat().st_size} for p in sorted(DATA_DIR.glob("*.csv"))
            if p.resolve().is_relative_to(DATA_DIR.resolve()) and p.stat().st_size <= MAX_CSV_BYTES]


@app.get("/ai/status")
def ai_status():
    with db.get_session() as session:
        run = selected_run(session)
        return {**llm_status(), "published_run_id": run.id if run else None,
                "actual_provider_counts": run.metrics.get("provider_counts", {}) if run else {},
                "score_semantics": "VADER signed compound intensity [-1, 1], not probability",
                "advisory": True}


@app.get("/dashboard/snapshot")
def dashboard_snapshot(run_id: UUID | None = None):
    with db.get_session() as session:
        return snapshot(session, str(run_id) if run_id else None)


@app.get("/dashboard/summary")
def dashboard_summary(run_id: UUID | None = None):
    with db.get_session() as session:
        result = snapshot(session, str(run_id) if run_id else None)
        if not result["summary"]:
            raise HTTPException(404, "No successful run yet. Analyze a dataset first.")
        return result["summary"]


@app.get("/reviews")
def get_reviews(sentiment: Literal["positive", "neutral", "negative"] | None = None,
                theme_id: int | None = Query(None, ge=1), run_id: UUID | None = None,
                limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0, le=20000)):
    with db.get_session() as session:
        run = selected_run(session, str(run_id) if run_id else None)
        if not run:
            return []
        query = select(db.Review).where(db.Review.run_id == run.id)
        if sentiment:
            query = query.where(db.Review.sentiment == sentiment)
        if theme_id is not None:
            query = query.where(db.Review.theme_id == theme_id)
        return [review_dict(r) for r in session.scalars(query.order_by(db.Review.id).offset(offset).limit(limit))]


@app.get("/themes")
def get_themes(run_id: UUID | None = None):
    with db.get_session() as session:
        return snapshot(session, str(run_id) if run_id else None)["themes"]


@app.get("/insights")
def get_insights(run_id: UUID | None = None):
    with db.get_session() as session:
        return snapshot(session, str(run_id) if run_id else None)["insights"]


@app.get("/runs")
def get_runs(limit: int = Query(20, ge=1, le=100)):
    with db.get_session() as session:
        return [run_dict(r) for r in session.scalars(select(db.AnalysisRun).order_by(db.AnalysisRun.started_at.desc()).limit(limit))]


@app.get("/runs/{run_id}/export")
def export_run(run_id: UUID):
    with db.get_session() as session:
        result = snapshot(session, str(run_id), export=True)
    return JSONResponse(result, headers={"Content-Disposition": f'attachment; filename="drivesense-{run_id}.json"'})


@app.post("/analyze")
def analyze(request: AnalyzeRequest):
    try:
        return execute_pipeline(request.csv_path, request.n_clusters, request.routing, request.backend)
    except (InputError, BusyError):
        raise
    except Exception as exc:
        # Do not expose local paths, input text, model response or credentials.
        logger.error("Analysis failed; error_code=%s", type(exc).__name__)
        raise HTTPException(500, "Analysis failed. The previous successful run is preserved; inspect /runs for the error code.") from exc


@app.post("/insights/{insight_id}/review")
def review_action(insight_id: int, request: ReviewRequest):
    with writer_lock(db.DB_PATH):
        with db.get_session() as session, session.begin():
            action = session.get(db.Insight, insight_id)
            if action is None:
                raise HTTPException(404, "Action not found.")
            if action.review_version != request.expected_version:
                raise HTTPException(409, "This action was reviewed elsewhere. Refresh before submitting.")
            version = action.review_version + 1
            edits = {key: value for key, value in request.model_dump().items()
                     if key in ("engineering_recommendation", "service_recommendation") and value}
            record = db.ReviewEvent(run_id=action.run_id, insight_id=action.id, version=version,
                decision=request.decision, reviewer=request.reviewer, note=request.note, edits=edits)
            session.add(record)
            action.review_version = version
            session.flush()
            result = event_dict(record)
    return result
