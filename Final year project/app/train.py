import argparse
import json

import pandas as pd

from app.catalog import DISEASES
from app.config import Settings
from app.ml import synthetic_data, train


def main():
    parser = argparse.ArgumentParser(
        description="Train unvalidated research models, never clinical models."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--demo", action="store_true", help="Generate explicitly synthetic examples for all modules"
    )
    source.add_argument("--csv", help="Local CSV with canonical features and binary target")
    parser.add_argument("--disease", choices=list(DISEASES), help="Required for --csv")
    parser.add_argument("--output", default=str(Settings().model_dir))
    args = parser.parse_args()
    if args.csv and not args.disease:
        parser.error("--csv requires --disease")
    if args.demo and args.disease:
        parser.error("--demo trains all three modules; omit --disease")
    diseases = DISEASES if args.demo else [args.disease]
    for disease in diseases:
        frame = synthetic_data(disease) if args.demo else pd.read_csv(args.csv)
        metadata = train(disease, frame, args.output, "synthetic" if args.demo else "local_csv")
        print(
            json.dumps(
                {
                    "disease": disease,
                    "source": metadata["source"],
                    "version": metadata["version"],
                    "metrics": metadata["metrics"],
                    "warning": "Not clinically validated. Synthetic metrics are not clinical performance.",
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
