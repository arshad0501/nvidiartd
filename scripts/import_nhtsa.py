"""Import a bounded official public complaint sample; never invent star ratings.

This is a compatibility case study, not independent sentiment/defect ground truth.
Only review summaries and vehicle fields are retained; common identifiers in
free text are redacted. Manual privacy review remains necessary before sharing.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import requests

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "https://api.nhtsa.gov/complaints/complaintsByVehicle"


def redact(text):
    text = re.sub(r"\b[A-HJ-NPR-Z0-9]{17}\b", "[VIN REDACTED]", text, flags=re.I)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[EMAIL REDACTED]", text)
    return re.sub(r"(?<!\d)(?:\+?1[ -]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)", "[PHONE REDACTED]", text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--make", default="TOYOTA")
    parser.add_argument("--model", default="CAMRY")
    parser.add_argument("--year", type=int, default=2019)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.limit <= 200 or not 1980 <= args.year <= 2030:
        parser.error("Limit must be 1–200 and year 1980–2030")
    params = {"make":args.make,"model":args.model,"modelYear":args.year}
    response = requests.get(ENDPOINT,params=params,timeout=45)
    response.raise_for_status()
    if len(response.content) > 15*1024*1024:
        raise ValueError("Unexpectedly large public-data response")
    payload = response.json()
    entries = payload.get("results", payload.get("Results", []))
    rows, identifiers = [], []
    for entry in entries:
        summary = str(entry.get("summary", entry.get("Summary", ""))).strip()
        if len(summary) < 10:
            continue
        rows.append({"vehicle":f"{args.make} {args.model} {args.year}","review_text":redact(summary)[:12000],"rating":""})
        identifiers.append(str(entry.get("odiNumber",entry.get("ODINumber","unknown"))))
        if len(rows) == args.limit:break
    if not rows:
        raise ValueError("Official source returned no usable summaries; do not substitute invented records")
    destination = ROOT/"data/nhtsa_public_sample.csv"
    with destination.open("w",newline="",encoding="utf8") as f:
        writer=csv.DictWriter(f,fieldnames=["vehicle","review_text","rating"]);writer.writeheader();writer.writerows(rows)
    provenance={"source":"NHTSA public complaints API","url":response.url,"retrieved_at":datetime.now(timezone.utc).isoformat(),
        "raw_response_sha256":hashlib.sha256(response.content).hexdigest(),"csv_sha256":hashlib.sha256(destination.read_bytes()).hexdigest(),
        "selection":"First usable summaries in API response order, bounded sample; not random or representative",
        "retained_rows":len(rows),"source_odi_numbers":identifiers,
        "preprocessing":"Summary only, common VIN/email/phone patterns redacted; text capped at 12000 characters; rating unknown",
        "limitations":["Owner reports are unverified allegations, not established defects.","Complaint-selected corpus has no noncomplaint control group.",
                       "No independent sentiment, category or expert severity labels.","Automated redaction is incomplete; manually review before sharing or hosted inference."]}
    (ROOT/"data/nhtsa_public_sample.provenance.json").write_text(json.dumps(provenance,indent=2),encoding="utf8")
    print(f"Imported {len(rows)} public summaries with unknown ratings; provenance saved.")


if __name__=="__main__":main()
