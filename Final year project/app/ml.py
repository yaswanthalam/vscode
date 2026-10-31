import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.catalog import DISEASES, validate_features


def synthetic_data(disease, rows=900, seed=42):
    rng = np.random.default_rng(seed)
    features = DISEASES[disease]["features"]
    frame = pd.DataFrame(
        {key: rng.uniform(spec[2], spec[3], rows) for key, spec in features.items()}
    )
    if "exercise_angina" in frame:
        frame["exercise_angina"] = rng.integers(0, 2, rows)
    normalized = np.column_stack(
        [(frame[key] - spec[2]) / (spec[3] - spec[2]) for key, spec in features.items()]
    )
    # Artificial labels deliberately have no clinical interpretation.
    weights = rng.uniform(-1, 2, normalized.shape[1])
    latent = normalized @ weights + rng.normal(0, 0.2, rows)
    frame["target"] = (latent > np.median(latent)).astype(int)
    return frame


def train(disease, frame, output, source="synthetic", seed=42):
    if disease not in DISEASES or source not in {"synthetic", "local_csv"}:
        raise ValueError("Invalid training configuration")
    keys = list(DISEASES[disease]["features"])
    if set(frame.columns) != set(keys + ["target"]):
        raise ValueError(f"CSV must contain exactly {keys + ['target']}")
    frame = frame.apply(pd.to_numeric, errors="raise")
    if len(frame) < 100 or frame["target"].isna().any():
        raise ValueError("Provide at least 100 rows and no missing target values")
    if set(frame["target"].unique()) != {0, 1} or frame["target"].value_counts().min() < 20:
        raise ValueError("Target must be 0/1 with at least 20 examples of each class")
    if frame.duplicated(subset=keys).any():
        raise ValueError("Duplicate feature rows must be resolved before splitting")
    for key, spec in DISEASES[disease]["features"].items():
        values = frame[key].dropna()
        if values.empty or not values.between(spec[2], spec[3]).all():
            raise ValueError(f"Invalid values or entirely missing column: {key}")
        if key == "exercise_angina" and not values.isin([0, 1]).all():
            raise ValueError("exercise_angina must be 0/1")
    x_train, x_test, y_train, y_test = train_test_split(
        frame[keys],
        frame["target"].astype(int),
        test_size=0.2,
        stratify=frame["target"],
        random_state=seed,
    )
    candidates = {
        "logistic_regression": make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            LogisticRegression(max_iter=1500, random_state=seed),
        ),
        "random_forest": make_pipeline(
            SimpleImputer(strategy="median"),
            RandomForestClassifier(n_estimators=100, max_depth=7, random_state=seed, n_jobs=1),
        ),
    }
    folds = StratifiedKFold(n_splits=4, shuffle=True, random_state=seed)
    scores = {
        name: float(cross_val_score(model, x_train, y_train, cv=folds, scoring="f1").mean())
        for name, model in candidates.items()
    }
    winner = max(scores, key=scores.get)
    pipeline = candidates[winner].fit(x_train, y_train)
    predicted = pipeline.predict(x_test)
    version = uuid.uuid4().hex[:12]
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    artifact = output / f"{disease}-{version}.joblib"
    joblib.dump(pipeline, artifact)
    manifest = {
        "schema_version": 1,
        "disease": disease,
        "version": version,
        "source": source,
        "clinically_validated": False,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "features": keys,
        "feature_specs": {k: list(v) for k, v in DISEASES[disease]["features"].items()},
        "sklearn_version": sklearn.__version__,
        "seed": seed,
        "rows": len(frame),
        "train_rows": len(x_train),
        "test_rows": len(x_test),
        "algorithm": winner,
        "cross_validation_f1": scores,
        "metrics": {
            "accuracy": float(accuracy_score(y_test, predicted)),
            "precision": float(precision_score(y_test, predicted, zero_division=0)),
            "recall": float(recall_score(y_test, predicted, zero_division=0)),
            "f1": float(f1_score(y_test, predicted, zero_division=0)),
            "confusion_matrix": confusion_matrix(y_test, predicted, labels=[0, 1]).tolist(),
        },
        "artifact": artifact.name,
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
    }
    temporary = output / f".{disease}-{version}.json"
    temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(temporary, output / f"{disease}.json")
    return manifest


class ModelStore:
    def __init__(self, settings):
        self.settings = settings
        self.models = {}
        self.metadata = {}
        for disease in DISEASES:
            manifest_path = settings.model_dir / f"{disease}.json"
            if not manifest_path.exists():
                continue
            metadata = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected_specs = {k: list(v) for k, v in DISEASES[disease]["features"].items()}
            if (
                metadata["schema_version"] != 1
                or metadata["disease"] != disease
                or metadata["features"] != list(expected_specs)
                or metadata["feature_specs"] != expected_specs
                or metadata["sklearn_version"] != sklearn.__version__
                or metadata["source"] not in {"synthetic", "local_csv"}
            ):
                raise ValueError("Incompatible model metadata: " + disease)
            if metadata["source"] == "synthetic" and not settings.allow_demo_models:
                raise ValueError("Synthetic models are disabled")
            path = (settings.model_dir / metadata["artifact"]).resolve()
            if path.parent != settings.model_dir.resolve():
                raise ValueError("Invalid model artifact path")
            if hashlib.sha256(path.read_bytes()).hexdigest() != metadata["sha256"]:
                raise ValueError("Model integrity check failed")
            # joblib is executable: only load locally trained, administrator-owned artifacts.
            self.models[disease] = joblib.load(path)
            self.metadata[disease] = metadata

    def predict(self, disease, values):
        values = validate_features(disease, values)
        if disease not in self.models:
            raise LookupError("Model unavailable. Run the training command, then restart the app.")
        frame = pd.DataFrame([values], columns=self.metadata[disease]["features"])
        score = float(self.models[disease].predict_proba(frame)[0, 1])
        return {
            "disease": disease,
            "features": values,
            "model_score": round(score, 4),
            "predicted_class": int(score >= 0.5),
            "threshold": 0.5,
            "model_version": self.metadata[disease]["version"],
            "model_source": self.metadata[disease]["source"],
            "clinically_validated": False,
        }
