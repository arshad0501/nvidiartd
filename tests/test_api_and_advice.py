import copy
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from app.api.main import app
from app.core import insights, db
from app.core.pipeline import execute_pipeline
from app.core.views import snapshot

ROW = {"vehicle":"Test EV","review_text":"The battery drains overnight.","rating":2}


def test_clean_start_readiness_and_empty_routes(client):
    assert client.get("/health").json()["status"] == "ready"
    assert client.get("/dashboard/snapshot").json()["run"] is None
    assert client.get("/dashboard/summary").status_code == 404
    for route in ("/reviews", "/themes", "/insights", "/runs"):
        assert client.get(route).json() == []


@pytest.mark.parametrize("value", [-1,0,None,31,True,"7"])
def test_invalid_cluster_input_rejected_before_mutation(client, value):
    assert client.post("/analyze",json={"n_clusters":value}).status_code == 422
    assert client.get("/runs").json() == []


@pytest.mark.parametrize("query", ["limit=-1", "limit=0", "limit=1001", "offset=-1", "sentiment=banana", "run_id=bad"])
def test_review_bounds(client, query):
    assert client.get("/reviews?"+query).status_code == 422


def test_input_error_does_not_leak_server_path(client, isolated):
    response = client.post("/analyze",json={"csv_path":str(isolated.parent/"secret.csv")})
    assert response.status_code == 400 and str(isolated.parent) not in response.text


def test_run_snapshot_export_history_and_review_conflict(client, csv_file):
    csv_file([ROW])
    first = client.post("/analyze",json={}).json()
    assert first["status"] == "complete"
    snap = client.get("/dashboard/snapshot").json()
    action = snap["insights"][0]
    assert snap["run"]["source_sha256"] == first["source_sha256"]
    assert action["provider"] == "Rule-based" and action["evidence"][0]["review_text"] == ROW["review_text"]
    payload = {"expected_version":0,"decision":"edited","reviewer":"Examiner demo",
               "note":"Recorded during an explicit demonstration, not a domain validation study.",
               "engineering_recommendation":"Please verify measured battery drain before choosing a repair."}
    response = client.post(f"/insights/{action['id']}/review",json=payload)
    assert response.status_code == 200 and response.json()["version"] == 1
    assert client.post(f"/insights/{action['id']}/review",json=payload).status_code == 409
    exported = client.get(f"/runs/{first['run_id']}/export").json()
    assert exported["reviews"][0]["run_id"] == first["run_id"]
    assert exported["insights"][0]["review_history"][0]["edits"]
    client.post("/analyze",json={"n_clusters":1})
    assert client.get("/dashboard/snapshot",params={"run_id":first["run_id"]}).json()["run"]["id"] == first["run_id"]
    assert client.get("/reviews",params={"run_id":first["run_id"],"theme_id":action["theme_id"]}).json()[0]["review_text"] == ROW["review_text"]


def test_all_positive_csv_returns_valid_empty_theme_set(client, csv_file):
    csv_file([{"vehicle":"X","review_text":"Excellent comfortable seats.","rating":5}])
    result = client.post("/analyze",json={}).json()
    assert result["themes_discovered"] == result["insights_generated"] == 0
    assert client.get("/dashboard/summary").json()["total_reviews"] == 1


def test_backend_attribution_after_timeout_is_persisted(client, csv_file, monkeypatch):
    csv_file([ROW])
    monkeypatch.setenv("NVIDIA_API_KEY","test-token-never-sent")
    monkeypatch.setenv("DRIVESENSE_ALLOW_EXTERNAL","1")
    def fail(_):raise TimeoutError("test-token-never-sent")
    monkeypatch.setattr(insights,"_call_nvidia_nim_batch",fail)
    assert client.post("/analyze",json={}).status_code == 200
    a = client.get("/insights").json()[0]
    assert a["provider"] == "Rule-based" and a["fallback_reason"] == "TimeoutError"
    monkeypatch.delenv("NVIDIA_API_KEY")
    assert client.get("/insights").json()[0]["provider"] == "Rule-based"
    assert "test-token-never-sent" not in client.get("/ai/status").text + str(a)


def test_key_alone_does_not_authorize_external_transfer(client, csv_file, monkeypatch):
    csv_file([ROW]);monkeypatch.setenv("NVIDIA_API_KEY","unused")
    call = Mock(side_effect=AssertionError("Must not send"))
    monkeypatch.setattr(insights,"_call_nvidia_nim_batch",call)
    client.post("/analyze",json={})
    assert not call.called
    assert client.get("/insights").json()[0]["fallback_reason"] == "external_transfer_not_enabled"


def valid_response(payload):
    return [{"theme_id":p["theme_id"],"severity":"Medium","main_issue":"Preliminary complaint requiring verification.",
             "engineering_recommendation":"Verify the report with a qualified engineering reviewer.",
             "service_recommendation":"Document diagnostics before selecting any repair action.",
             "evidence_ids":[p["representative_reviews"][0]["source_row"]]} for p in reversed(payload)]


@pytest.mark.parametrize("mutation", ["null", "severity", "wrong_id", "missing", "duplicate", "wrong_evidence", "empty_text", "string_id"])
def test_invalid_model_response_falls_back_atomically(csv_file, monkeypatch, mutation):
    csv_file([ROW,{"vehicle":"X","review_text":"The brakes failed.","rating":1}])
    monkeypatch.setenv("NVIDIA_API_KEY","unused");monkeypatch.setenv("DRIVESENSE_ALLOW_EXTERNAL","1")
    def bad(payload):
        result = valid_response(payload)
        if mutation == "null":result[0] = None
        elif mutation == "severity":result[0]["severity"] = "Banana"
        elif mutation == "wrong_id":result[0]["theme_id"] = 10000
        elif mutation == "missing":result.pop()
        elif mutation == "duplicate":result.append(result[0])
        elif mutation == "wrong_evidence":result[0]["evidence_ids"] = [99999]
        elif mutation == "empty_text":result[0]["main_issue"] = "        "
        elif mutation == "string_id":result[0]["theme_id"] = "0"
        return result
    monkeypatch.setattr(insights,"_call_nvidia_nim_batch",bad)
    execute_pipeline(n_clusters=2)
    with db.get_session() as s:
        actions = snapshot(s)["insights"]
    assert len(actions) == 2 and all(a["provider"] == "Rule-based" and a["fallback_reason"] for a in actions)


def test_reordered_valid_model_results_keep_correct_evidence(csv_file, monkeypatch):
    csv_file([ROW,{"vehicle":"X","review_text":"The brakes failed.","rating":1}])
    monkeypatch.setenv("NVIDIA_API_KEY","unused");monkeypatch.setenv("DRIVESENSE_ALLOW_EXTERNAL","1")
    monkeypatch.setattr(insights,"_call_nvidia_nim_batch",valid_response)
    execute_pipeline(n_clusters=2)
    with db.get_session() as s:
        result = snapshot(s)
    assert all(a["provider"] == "NVIDIA NIM" and a["fallback_reason"] is None for a in result["insights"])
    assert all(e["theme_id"] == a["theme_id"] for a in result["insights"] for e in a["evidence"])


def test_remote_client_and_untrusted_origin_rejected(isolated):
    with TestClient(app,client=("192.0.2.1",50000)) as remote:
        assert remote.get("/reviews").status_code == 403
    with TestClient(app,client=("127.0.0.1",50000)) as local:
        assert local.post("/analyze",json={},headers={"Origin":"https://untrusted.example"}).status_code == 403


def test_shared_access_requires_token(isolated, monkeypatch):
    monkeypatch.setenv("DRIVESENSE_ACCESS_MODE","shared")
    monkeypatch.setenv("DRIVESENSE_API_TOKEN","a-long-random-test-token-of-sufficient-size")
    with TestClient(app,client=("192.0.2.1",50000)) as remote:
        assert remote.get("/reviews").status_code == 401
        assert remote.get("/reviews",headers={"Authorization":"Bearer a-long-random-test-token-of-sufficient-size"}).status_code == 200
