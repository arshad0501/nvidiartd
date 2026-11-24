"""Sparse lexical explanations separated from interchangeable vector backends."""
from dataclasses import dataclass
import re
import numpy as np
from scipy import sparse
from sklearn.cluster import KMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS
from sklearn.preprocessing import normalize
from sklearn.metrics import pairwise_distances
from app.core.config import InputError

DOMAIN_TERMS = {
    "Battery & Charging Issues": ["battery", "batteries", "charge", "charging", "voltage", "range"],
    "Brake System Issues": ["brake", "brakes", "braking", "pedal"],
    "Infotainment & Software Issues": ["screen", "infotainment", "bluetooth", "carplay", "touchscreen", "app", "software", "voice assistant"],
    "Transmission & Drivetrain Issues": ["transmission", "shifting", "gear", "gears", "clutch"],
    "Interior Quality Issues": ["seat", "seats", "interior", "trim", "rattle", "rattling", "dashboard", "stitching"],
    "Service & Dealer Experience": ["dealer", "dealership", "service", "appointment", "warranty", "claim", "staff"],
    "Climate Control (HVAC) Issues": ["air conditioning", "conditioning", "heater", "climate", "vents", "cabin"],
}
LEAD = re.compile(r"^(?:(?:overall|so far|honestly|i have to say|unfortunately|to be honest|frustratingly)[,\s]+|i['’]m disappointed that\s+)", re.I)
STOP_WORDS = sorted(set(ENGLISH_STOP_WORDS) | {"unfortunately", "frustratingly", "disappointed", "car", "vehicle"})


def normalize_document(text):
    return LEAD.sub("", text.strip()).strip()


def phrase_present(phrase, text):
    return bool(re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text, re.I))


def component_matches(text):
    return {name: [term for term in terms if phrase_present(term, text)]
            for name, terms in DOMAIN_TERMS.items()
            if any(phrase_present(term, text) for term in terms)}


def name_theme(keywords):
    matches = component_matches(" ".join(keywords))
    if not matches:
        return "Emerging Theme: " + ", ".join(keywords[:3]) if keywords else "Unresolved lexical evidence"
    ordered = sorted(matches, key=lambda k: (-len(matches[k]), k))
    if len(ordered) > 1 and len(matches[ordered[0]]) == len(matches[ordered[1]]):
        return "Mixed component feedback"
    return ordered[0]


@dataclass
class Representation:
    vectors: object
    lexical: object
    vectorizer: object
    backend: str


def get_embeddings(texts, backend="tfidf", preprocess=True):
    """Both backends retain a separate sparse vocabulary for explanation."""
    if backend not in ("tfidf", "lsa"):
        raise InputError("Embedding backend must be tfidf or lsa.")
    docs = [normalize_document(t) for t in texts] if preprocess else list(texts)
    vectorizer = TfidfVectorizer(max_features=2000, stop_words=STOP_WORDS if preprocess else "english",
                                 ngram_range=(1, 2), sublinear_tf=True)
    lexical = vectorizer.fit_transform(docs)
    vectors = lexical
    actual = "tfidf"
    if backend == "lsa" and min(lexical.shape) > 2:
        components = min(64, lexical.shape[0]-1, lexical.shape[1]-1)
        vectors = normalize(TruncatedSVD(n_components=components, random_state=42).fit_transform(lexical))
        actual = "lsa"
    return Representation(vectors, lexical, vectorizer, actual)


def validate_representation(rep, n_samples):
    if len(rep.vectors.shape) != 2 or rep.vectors.shape[0] != n_samples or rep.lexical.shape[0] != n_samples:
        raise InputError("Embedding backend returned an invalid matrix shape.")
    values = rep.vectors.data if sparse.issparse(rep.vectors) else np.asarray(rep.vectors)
    if not np.isfinite(values).all():
        raise InputError("Embedding backend returned non-finite values.")


def top_keywords_for_cluster(vectorizer, matrix, labels, cluster_id, n=8):
    mask = labels == cluster_id
    if not mask.any():
        return []
    weights = np.asarray(matrix[mask].mean(axis=0)).ravel()
    indices = np.argsort(-weights, kind="stable")[:n]
    names = vectorizer.get_feature_names_out()
    return [str(names[i]) for i in indices if weights[i] > 0]


def _distinct_rows(matrix):
    if sparse.issparse(matrix):
        m = matrix.tocsr()
        return len({(m[i].indices.tobytes(), np.round(m[i].data, 10).tobytes()) for i in range(m.shape[0])})
    return len(np.unique(np.round(matrix, 10), axis=0))


def discover_themes(records, n_clusters=7, backend="tfidf", preprocess=True, embedding_backend=None):
    if type(n_clusters) is not int or not 1 <= n_clusters <= 30:
        raise InputError("Cluster count must be an integer from 1 to 30.")
    selected = [i for i, record in enumerate(records) if record["complaint_candidate"]]
    if not selected:
        return [], {}, {"candidate_count": 0, "actual_k": 0, "warnings": []}
    texts = [records[i]["review_text"] for i in selected]
    try:
        rep = embedding_backend(texts) if embedding_backend else get_embeddings(texts, backend, preprocess)
    except ValueError as exc:
        if "empty vocabulary" not in str(exc):
            raise
        theme = {"local_id": 0, "theme_name": "Unresolved lexical evidence", "keywords": [],
                 "members": selected, "representatives": selected[:3],
                 "explanation": {"method": "empty-vocabulary fallback", "uncertain": True,
                                 "representative_selection": "source order; no lexical vectors available"}}
        return [theme], {i: 0 for i in selected}, {"candidate_count": len(selected), "actual_k": 1,
                    "warnings": ["No usable lexical tokens; evidence requires manual grouping."]}
    validate_representation(rep, len(selected))
    distinct = _distinct_rows(rep.vectors)
    k = max(1, min(n_clusters, len(selected), distinct))
    labels = KMeans(n_clusters=k, random_state=42, n_init=10).fit_predict(rep.vectors) if k > 1 else np.zeros(len(selected), dtype=int)
    themes = []
    for cluster_id in sorted(set(labels)):
        positions = np.flatnonzero(labels == cluster_id)
        keywords = top_keywords_for_cluster(rep.vectorizer, rep.lexical, labels, cluster_id)
        part = rep.vectors[positions]
        center = np.asarray(part.mean(axis=0)).reshape(1, -1)
        distances = pairwise_distances(part, center, metric="euclidean").ravel()
        ordered = list(np.argsort(distances, kind="stable"))
        # Closest review, then nearest distinct text, then a diverse outlier.
        picks, seen = [], set()
        for p in ordered + list(reversed(ordered)):
            if texts[positions[p]] not in seen:
                picks.append(int(positions[p])); seen.add(texts[positions[p]])
            if len(picks) == 2:
                break
        for p in reversed(ordered):
            if texts[positions[p]] not in seen:
                picks.append(int(positions[p])); break
        name = name_theme(keywords)
        themes.append({"local_id": int(cluster_id), "theme_name": name, "keywords": keywords,
                       "members": [selected[int(p)] for p in positions],
                       "representatives": [selected[p] for p in picks],
                       "explanation": {"method": "mean sparse TF-IDF weights; token/phrase component rules",
                           "backend": rep.backend, "uncertain": name.startswith(("Emerging", "Mixed", "Unresolved")),
                           "component_matches": component_matches(" ".join(keywords)),
                           "representative_selection": "nearest distinct central reviews plus distant distinct example"}})
    counts = {}
    for t in themes:
        counts[t["theme_name"]] = counts.get(t["theme_name"], 0) + 1
    for t in themes:
        if counts[t["theme_name"]] > 1:
            t["theme_name"] += f" / {', '.join(t['keywords'][:2])} / cluster {t['local_id']+1}"
    warnings = [f"Requested {n_clusters}; used {k} distinct clusters."] if k != n_clusters else []
    return themes, {selected[i]: int(label) for i, label in enumerate(labels)}, {
        "candidate_count": len(selected), "actual_k": len(themes), "requested_k": n_clusters,
        "backend": rep.backend, "feature_count": int(rep.lexical.shape[1]), "warnings": warnings}
