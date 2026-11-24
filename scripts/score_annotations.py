"""Check genuinely completed independent labels; do not manufacture agreement."""
import argparse
from pathlib import Path
import csv
import json
from sklearn.metrics import cohen_kappa_score


def read_sheet(path):
    with Path(path).open(encoding="utf-8-sig",newline="") as f:rows=list(csv.DictReader(f))
    if not rows or len({r["id"] for r in rows})!=len(rows):
        raise ValueError("Empty sheet or duplicate record identifiers")
    for r in rows:
        if r["sentiment"] not in ("positive","negative","neutral","mixed") or r["complaint"] not in ("yes","no","uncertain"):
            raise ValueError("Every record needs an independent valid sentiment and complaint label; blank labels cannot be scored")
    return {r["id"]:r for r in rows}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("annotator_a");p.add_argument("annotator_b");p.add_argument("--output",required=True)
    args=p.parse_args();a,b=read_sheet(args.annotator_a),read_sheet(args.annotator_b)
    if set(a)!=set(b):raise ValueError("Annotators must label the same record IDs")
    ids=sorted(a)
    result={"n":len(ids),"sentiment_kappa":float(cohen_kappa_score([a[i]["sentiment"] for i in ids],[b[i]["sentiment"] for i in ids])),
        "complaint_kappa":float(cohen_kappa_score([a[i]["complaint"] for i in ids],[b[i]["complaint"] for i in ids])),
        "disagreement_ids":[i for i in ids if any(a[i][k]!=b[i][k] for k in ("sentiment","complaint","aspects"))],
        "next_step":"Adjudicate disagreements without looking at predictions, then evaluate frozen held-out test split separately by source."}
    Path(args.output).write_text(json.dumps(result,indent=2),encoding="utf8")
    print("Saved agreement and disagreement IDs; no adjudicated labels invented.")


if __name__=="__main__":main()
