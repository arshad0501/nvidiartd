import os
for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[name] = "1"

import pytest
from app.core import db, config


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("DRIVESENSE_ALLOW_EXTERNAL", raising=False)
    monkeypatch.setenv("DRIVESENSE_ACCESS_MODE", "local")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    db.configure_database(tmp_path / "test.db")
    db.init_db()
    yield tmp_path
    db.engine.dispose()


@pytest.fixture
def client(isolated):
    from fastapi.testclient import TestClient
    from app.api.main import app
    with TestClient(app, client=("127.0.0.1", 50000), raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def csv_file(isolated):
    import pandas as pd
    def write(rows, name="reviews_raw.csv"):
        path = isolated / name
        pd.DataFrame(rows, columns=["vehicle", "review_text", "rating"]).to_csv(path, index=False)
        return path
    return write
