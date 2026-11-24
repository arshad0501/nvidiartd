"""Reproducible exploratory comparisons; no independent labels are invented."""
import os
for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[name] = "1"
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import csv
import hashlib
import importlib.util
import json
import statistics
import time
import tracemalloc
import numpy as np
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import (precision_recall_fscore_support, confusion_matrix, adjusted_rand_score,
                             silhouette_score)
from app.core.ingestion import load_reviews, clean_reviews
from app.core.sentiment import score_text, _analyzer
from app.core.complaints import complaint_evidence
from app.core.clustering import normalize_document, STOP_WORDS, get_embeddings

OUT = ROOT/"experiments/results"
OUT.mkdir(parents=True, exist_ok=True)


def write_csv(name, rows):
    with (OUT/name).open("w", encoding="utf8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys());writer.writeheader();writer.writerows(rows)


def binary_metrics(y, pred):
    p,r,f,_ = precision_recall_fscore_support(y,pred,average="binary",zero_division=0)
    return {"precision":float(p),"recall":float(r),"f1":float(f),
            "confusion_TN_FP_FN_TP":confusion_matrix(y,pred,labels=[False,True]).ravel().tolist()}


def main():
    spec = importlib.util.spec_from_file_location("generator", ROOT/"data/generate_sample_data.py")
    generator = importlib.util.module_from_spec(spec);spec.loader.exec_module(generator)
    lookup = {}
    for category, definition in generator.THEMES.items():
        for sentiment in ("positive","negative"):
            for base in definition[sentiment]:
                for lead in [""] + (generator.POS_LEAD if sentiment == "positive" else generator.NEG_LEAD):
                    text = f"{lead} {base[0].lower()}{base[1:]}" if lead else base
                    lookup[text] = {"category":category,"negative":sentiment=="negative","template_group":hashlib.sha256(base.encode()).hexdigest()[:12]}
    frame = clean_reviews(load_reviews(ROOT/"data/reviews_raw.csv"))
    assert all(t in lookup for t in frame.review_text), "Do not guess labels for unmatched input"
    texts=list(frame.review_text); target=[lookup[t]["negative"] for t in texts]
    original = [_analyzer.polarity_scores(t)["compound"] < 0 for t in texts]
    negative_only = [score_text(t)[0] == "negative" for t in texts]
    aware = [complaint_evidence(t,score_text(t)[0])[0] for t in texts]
    rating = [int(r)<=3 for r in frame.rating]
    metrics={name:binary_metrics(target,pred) for name,pred in {"original_binary_gate":original,
        "negative_only_v2":negative_only,"complaint_aware_v2":aware,"rating_only_weak_baseline":rating}.items()}
    predictions=[{"source_row":int(row.source_row),"template_group":lookup[row.review_text]["template_group"],
        "intended_negative":lookup[row.review_text]["negative"],"category":lookup[row.review_text]["category"],
        "original_gate":original[i],"negative_only_v2":negative_only[i],"complaint_aware_v2":aware[i]}
        for i,row in enumerate(frame.itertuples(index=False))]
    write_csv("routing_predictions.csv",predictions)
    groups=sorted({lookup[t]["template_group"] for t in texts})
    # Group bootstrap accounts for repeated variants of each base template.
    rng=np.random.default_rng(2026); delta=[]
    for _ in range(1000):
        sampled=rng.choice(groups,size=len(groups),replace=True)
        indices=[i for g in sampled for i,t in enumerate(texts) if lookup[t]["template_group"]==g]
        yy=[target[i] for i in indices]
        delta.append(binary_metrics(yy,[aware[i] for i in indices])["recall"]-binary_metrics(yy,[original[i] for i in indices])["recall"])
    # Fixed corpus for representation comparison avoids changing membership when comparing vectors.
    selected=[i for i,v in enumerate(aware) if v]
    corpus=[texts[i] for i in selected];truth=[lookup[t]["category"] for t in corpus]
    comparison=[];partitions={}
    representations={
        "original_500_raw":lambda:TfidfVectorizer(max_features=500,stop_words="english",ngram_range=(1,2)).fit_transform(corpus),
        "500_discourse_removed":lambda:TfidfVectorizer(max_features=500,stop_words=STOP_WORDS,ngram_range=(1,2)).fit_transform([normalize_document(t) for t in corpus]),
        "v2_tfidf":lambda:get_embeddings(corpus,"tfidf").vectors,
        "v2_lsa":lambda:get_embeddings(corpus,"lsa").vectors,
    }
    for method,build in representations.items():
        matrix=build()
        for k in range(3,13):
            for seed in (42,7,99):
                start=time.perf_counter()
                labels=KMeans(n_clusters=k,random_state=seed,n_init=10).fit_predict(matrix)
                partitions[(method,k,seed)]=labels
                comparison.append({"method":method,"k":k,"seed":seed,
                    "ARI_generator_category":float(adjusted_rand_score(truth,labels)),
                    "silhouette_cosine":float(silhouette_score(matrix,labels,metric="cosine")),
                    "fit_seconds":time.perf_counter()-start})
    write_csv("representation_comparison.csv",comparison)
    stability=[{"method":method,"k":k,"pairwise_seed_ARI_mean":statistics.mean(adjusted_rand_score(partitions[method,k,a],partitions[method,k,b]) for a,b in [(42,7),(42,99),(7,99)])}
               for method in representations for k in range(3,13)]
    write_csv("seed_stability.csv",stability)
    # Isolated keyword-extraction allocation benchmark: same matrix/labels,
    # original dense-per-cluster versus sparse means. Not predictive validation.
    repeated=corpus*10
    matrix=TfidfVectorizer(max_features=2000,stop_words="english",ngram_range=(1,2)).fit_transform(repeated)
    labels=np.arange(len(repeated))%7
    allocation=[]
    for method in ("dense_per_cluster", "sparse_means"):
        tracemalloc.start();start=time.perf_counter()
        for k in range(7):
            m=matrix.toarray() if method=="dense_per_cluster" else matrix
            _=np.asarray(m[labels==k].mean(axis=0)).ravel()
        _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
        allocation.append({"method":method,"records":len(repeated),"features":matrix.shape[1],
            "seconds":time.perf_counter()-start,"peak_traced_MiB":peak/1024**2})
    write_csv("keyword_allocation.csv",allocation)
    result={"scope":"Exploratory supplied synthetic corpus; reconstructed generator intent, no independent human ground truth or held-out test",
        "input_sha256":frame.attrs["source_sha256"],"clean_rows":len(frame),"unique_text":len(set(texts)),
        "base_template_groups":len(groups),"routing":metrics,
        "recall_difference_group_bootstrap_95_interval":np.percentile(delta,[2.5,97.5]).tolist(),
        "clustering_corpus":"Same complaint-aware candidate set for all four representation comparisons",
        "candidate_count":len(corpus),"keyword_allocation":allocation,
        "cautions":["Rating baseline is circular: generator selects ratings from intended sentiment; not a fair independent predictor.",
                    "All K and representation results are reported; no best K claimed from this exploratory corpus.",
                    "Silhouette values from LSA and TF-IDF are not directly comparable as quality rankings.",
                    "Bootstrap intervals quantify variation across these templates, not real-world generalization.",
                    "No expert advice utility or manual triage speedup measured."]}
    (OUT/"benchmark_results.json").write_text(json.dumps(result,indent=2),encoding="utf8")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(11,4))
    names=["original_binary_gate","negative_only_v2","complaint_aware_v2"]
    axes[0].bar(["Original gate","Neutral kept","Complaint cues"],[metrics[n]["recall"] for n in names],color=["#788b82","#508d77","#174d3e"])
    axes[0].set(ylim=(0,1),ylabel="Recall against generator intent",title="Synthetic routing diagnostic")
    for method in representations:
        means=[statistics.mean(r["ARI_generator_category"] for r in comparison if r["method"]==method and r["k"]==k) for k in range(3,13)]
        axes[1].plot(range(3,13),means,marker="o",label=method)
    axes[1].set(xlabel="Requested K",ylabel="Category ARI",title="Fixed candidate corpus, mean of three seeds");axes[1].legend(fontsize=8)
    fig.tight_layout();fig.savefig(OUT/"comparisons.png",dpi=160);plt.close(fig)
    print(json.dumps(result,indent=2))


if __name__=="__main__":main()
