"""Optional Python dashboard. React is the canonical interface."""
import os
import requests
import pandas as pd
import plotly.express as px
import streamlit as st

API = os.environ.get("DRIVESENSE_API", "http://127.0.0.1:8000")
headers = {"Authorization": "Bearer " + os.environ["DRIVESENSE_API_TOKEN"]} if os.environ.get("DRIVESENSE_API_TOKEN") else {}


def request(method, route, **kwargs):
    response = requests.request(method, API+route, headers=headers, timeout=90, **kwargs)
    response.raise_for_status()
    return response.json()


st.set_page_config(page_title="DriveSense AI", layout="wide")
st.title("DriveSense AI")
st.caption("Evidence-linked automotive complaint triage. Synthetic demo data; human review required.")
with st.sidebar:
    st.header("Analysis")
    k = st.number_input("Requested clusters", min_value=1, max_value=30, value=7)
    routing = st.selectbox("Routing", ["complaint_aware", "negative_only"])
    backend = st.selectbox("Representation", ["tfidf", "lsa"])
    if st.button("Run full analysis", type="primary"):
        try:
            with st.spinner("Computing a new run; existing results remain available…"):
                result = request("POST", "/analyze", json={"n_clusters":int(k), "routing":routing, "backend":backend})
            st.success("Published run " + result["run_id"][:8])
        except requests.RequestException:
            st.error("Analysis failed or timed out. The previous successful run is preserved; inspect the API run history.")
    st.info("Use React on port 5173 for review decisions, history selection and evidence export.")
try:
    data = request("GET", "/dashboard/snapshot")
except requests.RequestException:
    st.error("Cannot load the API. Start uvicorn on 127.0.0.1:8000 and verify its health endpoint.")
    st.stop()
if not data["summary"]:
    st.info("No successful run yet. Run analysis in the sidebar.")
    st.stop()
run, summary = data["run"], data["summary"]
st.caption(f"Run {run['id']} / input SHA-256 {run['source_sha256']}")
st.write("Actual recommendation providers:", run["metrics"].get("provider_counts", {}))
overview, themes, actions = st.tabs(["Overview", "Theme evidence", "Advisory actions"])
with overview:
    cols = st.columns(4)
    for col, title, value in zip(cols, ["Reviews", "Complaint candidates", "Neutral polarity", "Themes"],
            [summary["total_reviews"], summary["complaint_candidates"], summary["neutral_reviews"], summary["theme_count"]]):
        col.metric(title,value)
    dist = pd.DataFrame({"Sentiment":["Positive","Neutral","Negative"],
                         "Count":[summary["positive_reviews"],summary["neutral_reviews"],summary["negative_reviews"]]})
    st.plotly_chart(px.bar(dist,x="Sentiment",y="Count"),use_container_width=True)
    st.write("Cleaning report",run["cleaning"])
    for warning in run["metrics"].get("warnings",[]):st.warning(warning)
with themes:
    if data["themes"]:
        chosen = st.selectbox("Theme",data["themes"],format_func=lambda t:t["theme_name"])
        st.write("Keywords:",chosen["keywords"])
        try:
            rows = request("GET","/reviews",params={"theme_id":chosen["id"],"run_id":run["id"],"limit":25})
            st.dataframe(pd.DataFrame(rows)[["vehicle","review_text","rating","sentiment","sentiment_score"]],hide_index=True)
            st.caption("sentiment_score = signed VADER compound [-1,1], not a confidence probability.")
        except requests.RequestException:
            st.error("Could not load this run's review evidence.")
    else:st.info("This run has no complaint themes.")
with actions:
    for a in data["insights"]:
        with st.expander(a["severity"]+" / "+a["theme_name"]):
            st.write("Provider:",a["provider"],"Model:",a["model"],"Fallback:",a["fallback_reason"])
            st.write(a["main_issue"])
            st.write("Engineering:",a["engineering_recommendation"])
            st.write("Service:",a["service_recommendation"])
            for evidence in a["evidence"]:
                st.write(f"Source row {evidence['source_row']}: {evidence['review_text']}")
            st.warning("Advisory only. Review and validate before operational decisions.")
