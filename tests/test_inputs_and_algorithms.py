import hashlib
import subprocess
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from app.core.ingestion import clean_reviews
from app.core.sentiment import score_text
from app.core.complaints import complaint_evidence
from app.core.clustering import (name_theme, discover_themes, get_embeddings, Representation, component_matches)
from app.core.pipeline import execute_pipeline
from app.core.config import InputError, resolve_csv


def test_missing_and_invalid_ratings_are_not_invented():
    raw = pd.DataFrame([{"vehicle":"X","review_text":"bad  brakes","rating":None},
        {"vehicle":"X","review_text":"bad brakes","rating":None},
        {"vehicle":"X","review_text":"Other report","rating":2.5},
        {"vehicle":"X","review_text":"Third report","rating":7},
        {"vehicle":"X","review_text":"Fourth report","rating":"unknown"}])
    cleaned = clean_reviews(raw)
    assert len(cleaned) == 1 and pd.isna(cleaned.iloc[0].rating)
    assert cleaned.iloc[0].review_text == "bad brakes"
    assert cleaned.attrs["cleaning"]["invalid_rating_rows"] == 3
    assert cleaned.attrs["cleaning"]["duplicate_rows"] == 1
    with pytest.raises(InputError, match="Missing CSV"):
        clean_reviews(raw.drop(columns=["rating"]))


@pytest.mark.parametrize("text", ["", "   ", "nan", "None"])
def test_junk_review_rejected(text):
    assert clean_reviews(pd.DataFrame([{"vehicle":"X","review_text":text,"rating":3}])).empty


def test_polarity_is_signed_and_neutral_retained():
    assert score_text("The vehicle is blue.") == ("neutral", 0)
    assert score_text("Excellent wonderful car")[1] > 0
    assert score_text("Terrible horrible car")[1] < 0


def test_component_phrase_boundaries():
    assert "Infotainment" not in name_theme(["disappointed"])
    assert name_theme(["app", "freezes"]) == "Infotainment & Software Issues"
    assert name_theme(["air conditioning", "heater"]) == "Climate Control (HVAC) Issues"
    assert not component_matches("I appreciate this approach")


@pytest.mark.parametrize("text", ["The battery drains overnight.", "I love the styling but the brakes failed.", "The screen freezes every morning."])
def test_mixed_or_factual_complaints_are_candidates(text):
    yes, evidence = complaint_evidence(text, score_text(text)[0])
    assert yes and evidence
    for span in evidence:
        if span["start"] is not None:
            assert text[span["start"]:span["end"]] == span["span"]


def test_absent_symptom_and_positive_component_do_not_route():
    assert not complaint_evidence("No rattles and no leaks; excellent cabin.", "positive")[0]
    assert not complaint_evidence("The brakes are excellent.", "positive")[0]


@pytest.mark.parametrize("texts,expected", [([],0),(["bad brakes"],1),(["the and or"],1),(["bad brakes"]*4,1)])
def test_tiny_and_tokenpoor_clustering(texts, expected):
    records = [{"review_text":t,"complaint_candidate":True} for t in texts]
    themes, assignments, metrics = discover_themes(records, 7)
    assert len(themes) == expected and len(assignments) == len(texts)
    assert sum(len(t["members"]) for t in themes) == len(texts)


def test_sparse_and_dense_backend_contracts():
    records = [{"review_text":t,"complaint_candidate":True} for t in ["brakes failed", "battery drains", "screen freezes", "gear shifts roughly"]]
    for backend in ("tfidf", "lsa"):
        themes, _, metrics = discover_themes(records, 2, backend)
        assert len(themes) == 2 and themes[0]["keywords"]
    def dense(texts):
        rep = get_embeddings(texts)
        return Representation(np.eye(len(texts)), rep.lexical, rep.vectorizer, "fake-dense-contract")
    assert len(discover_themes(records, 2, embedding_backend=dense)[0]) == 2
    def invalid(texts):
        rep = dense(texts);rep.vectors[0,0] = np.nan;return rep
    with pytest.raises(InputError):
        discover_themes(records, 2, embedding_backend=invalid)


def test_empty_usable_input_preserves_run(csv_file):
    csv_file([{"vehicle":"X","review_text":"Great car","rating":5}])
    execute_pipeline()
    csv_file([{"vehicle":"","review_text":"","rating":None}])
    with pytest.raises(InputError): execute_pipeline()


def test_path_escape_and_non_csv_rejected(isolated):
    with pytest.raises(InputError):resolve_csv(isolated.parent / "private.csv")
    with pytest.raises(InputError):resolve_csv("../private.csv")
    (isolated/"x.txt").write_text("hi")
    with pytest.raises(InputError):resolve_csv("x.txt")


def test_generator_is_reproducible_from_other_working_directory(tmp_path):
    script = Path(__file__).resolve().parents[1]/"data/generate_sample_data.py"
    for name in ["a.csv", "b.csv"]:
        subprocess.run([sys.executable,str(script),"--output",str(tmp_path/name)],cwd=tmp_path,check=True,capture_output=True)
    assert (tmp_path/"a.csv").read_bytes() == (tmp_path/"b.csv").read_bytes()
