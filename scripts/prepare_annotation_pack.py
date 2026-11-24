"""Create blinded blank annotation sheets. Never generate human labels."""
from pathlib import Path
import csv
import hashlib
import json
import random
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.core.ingestion import load_reviews, clean_reviews
from data.generate_sample_data import THEMES, POS_LEAD, NEG_LEAD


def main():
    out=ROOT/"evaluation_data/annotation_pack"
    out.mkdir(parents=True,exist_ok=True)
    templates={}
    for definition in THEMES.values():
        for label in ("positive","negative"):
            for base in definition[label]:
                for lead in [""]+(POS_LEAD if label=="positive" else NEG_LEAD):
                    text=f"{lead} {base[0].lower()}{base[1:]}" if lead else base
                    templates[text]=hashlib.sha256(base.encode()).hexdigest()[:12]
    rng=random.Random(2026);items=[]
    for name in ["reviews_raw.csv","nhtsa_public_sample.csv"]:
        path=ROOT/"data"/name
        if not path.exists():continue
        frame=clean_reviews(load_reviews(path)).drop_duplicates("review_text")
        rows=frame.to_dict("records");rng.shuffle(rows)
        for row in rows[:80]:
            digest=hashlib.sha256(row["review_text"].encode()).hexdigest()
            group=templates.get(row["review_text"],digest[:12])
            items.append({"id":digest[:16],"vehicle":row["vehicle"],"review_text":row["review_text"],
                          "group":group,"source":name,"split":"test" if int(hashlib.sha256(group.encode()).hexdigest()[:8],16)%5==0 else "development"})
    rng.shuffle(items)
    fields=["id","vehicle","review_text","sentiment","complaint","aspects","notes"]
    for annotator in ["A","B"]:
        destination=out/f"annotator_{annotator}.csv"
        if destination.exists():
            print(f"Preserved existing {destination.name}");continue
        with destination.open("w",newline="",encoding="utf8") as f:
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
            writer.writerows({**{key:item[key] for key in fields if key in item},
                "sentiment":"","complaint":"","aspects":"","notes":""} for item in items)
    manifest={"seed":2026,"labels_status":"blank; independent annotators and adjudication required",
              "warning":"Public sample contains complaint-selected reports, synthetic rows are repetitive; report sources separately.",
              "items":[{k:v for k,v in item.items() if k not in ["vehicle","review_text"]} for item in items]}
    (out/"split_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf8")
    print(f"Prepared {len(items)} blinded records. Human label fields are blank.")


if __name__=="__main__":main()
