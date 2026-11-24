"""Atomic CLI entry point. Input must be within DRIVESENSE_DATA_DIR."""
import argparse
import json
from app.core.config import InputError, BusyError
from app.core.pipeline import execute_pipeline


def main():
    parser = argparse.ArgumentParser(description="Analyze automotive reviews; preserve run history and last successful output.")
    parser.add_argument("--csv", default=None, help="CSV name or path within configured data directory")
    parser.add_argument("--clusters", type=int, default=7)
    parser.add_argument("--routing", choices=["complaint_aware", "negative_only"], default="complaint_aware")
    parser.add_argument("--backend", choices=["tfidf", "lsa"], default="tfidf")
    args = parser.parse_args()
    try:
        result = execute_pipeline(args.csv, args.clusters, args.routing, args.backend)
    except (InputError, BusyError) as exc:
        parser.exit(2, f"Analysis not started: {exc}\n")
    print(json.dumps(result, indent=2))
    print("API: uvicorn app.api.main:app --host 127.0.0.1 --port 8000")
    print("React: cd frontend then npm run dev")


if __name__ == "__main__":
    main()
