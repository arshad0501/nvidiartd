"""CSV validation with an explicit, countable reject policy; no database writes."""
from io import BytesIO
import hashlib
import numpy as np
import pandas as pd
from app.core.config import InputError, MAX_CSV_BYTES, MAX_REVIEWS, MAX_TEXT_LENGTH


def load_reviews(csv_path):
    with open(csv_path, "rb") as f:
        payload = f.read(MAX_CSV_BYTES + 1)
    if len(payload) > MAX_CSV_BYTES:
        raise InputError("CSV exceeds the 10 MiB input limit.")
    try:
        df = pd.read_csv(BytesIO(payload), encoding="utf-8-sig", nrows=MAX_REVIEWS + 1)
    except (ValueError, UnicodeError, pd.errors.ParserError) as exc:
        raise InputError("Cannot parse UTF-8 CSV with a header row.") from exc
    if len(df) > MAX_REVIEWS:
        raise InputError(f"CSV exceeds the {MAX_REVIEWS:,} row limit.")
    df.attrs["source_sha256"] = hashlib.sha256(payload).hexdigest()
    return df


def clean_reviews(df):
    missing = sorted({"vehicle", "review_text", "rating"} - set(df.columns))
    if missing:
        raise InputError("Missing CSV columns: " + ", ".join(missing))
    result = df.copy()
    result["source_row"] = np.arange(2, len(result) + 2)
    for field in ("vehicle", "review_text"):
        result[field] = result[field].astype("string").fillna("").str.replace(r"\s+", " ", regex=True).str.strip()
    valid_text = (~result.review_text.str.lower().isin(["", "nan", "none", "null"]) &
                  ~result.vehicle.str.lower().isin(["", "nan", "none", "null"]) &
                  result.review_text.str.len().le(MAX_TEXT_LENGTH) & result.vehicle.str.len().le(128))
    bad_text = int((~valid_text).sum())
    result = result.loc[valid_text].copy()
    # Missing ratings stay unknown; present malformed values are rejected.
    missing_rating = result.rating.isna() | result.rating.astype(str).str.strip().eq("")
    numeric = pd.to_numeric(result.rating, errors="coerce")
    valid_rating = missing_rating | (numeric.between(1, 5) & numeric.mod(1).eq(0))
    bad_rating = int((~valid_rating).sum())
    result = result.loc[valid_rating].copy()
    result["rating"] = numeric.loc[result.index].astype("Int64")
    before = len(result)
    result = result.drop_duplicates(["vehicle", "review_text"]).reset_index(drop=True)
    report = {"raw_rows": len(df), "invalid_text_rows": bad_text,
              "invalid_rating_rows": bad_rating, "duplicate_rows": before-len(result),
              "clean_rows": len(result), "missing_ratings": int(result.rating.isna().sum()),
              "policy": "Reject invalid present ratings/text; preserve missing ratings; dedupe normalized vehicle/text."}
    assert report["raw_rows"] == sum(report[k] for k in ["invalid_text_rows", "invalid_rating_rows", "duplicate_rows", "clean_rows"])
    result.attrs.update(df.attrs)
    result.attrs["cleaning"] = report
    return result
