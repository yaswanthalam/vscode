import json

import pytest

from app.config import Settings
from app.ml import ModelStore, synthetic_data, train


def test_training_rejects_bad_schema_labels_duplicates_and_ranges(tmp_path):
    frame = synthetic_data("diabetes", rows=120)
    for bad in [
        frame.drop(columns=["glucose"]),
        frame.assign(target=1),
        frame.assign(glucose=-1),
        frame.assign(glucose=float("nan")),
        frame.iloc[:20],
    ]:
        with pytest.raises(ValueError):
            train("diabetes", bad, tmp_path)
    duplicate = frame.copy()
    duplicate.iloc[1] = duplicate.iloc[0]
    with pytest.raises(ValueError, match="Duplicate"):
        train("diabetes", duplicate, tmp_path)


def test_csv_pipeline_and_integrity(settings, tmp_path):
    frame = synthetic_data("diabetes", rows=140)
    frame.loc[0, "glucose"] = float("nan")
    metadata = train("diabetes", frame, tmp_path, source="local_csv")
    settings.model_dir = tmp_path
    settings.allow_demo_models = False
    store = ModelStore(settings)
    assert store.metadata["diabetes"]["source"] == "local_csv"
    assert metadata["train_rows"] + metadata["test_rows"] == metadata["rows"]
    assert len(metadata["metrics"]["confusion_matrix"]) == 2
    assert metadata["clinically_validated"] is False
    artifact = tmp_path / metadata["artifact"]
    artifact.write_bytes(artifact.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="integrity"):
        ModelStore(settings)


def test_demo_and_production_guards(settings):
    settings.allow_demo_models = False
    with pytest.raises(ValueError, match="Synthetic"):
        ModelStore(settings)
    with pytest.raises(ValueError, match="Production"):
        Settings(_env_file=None, app_env="production").validate_deployment()


def test_schema_drift_rejected(settings, tmp_path):
    metadata = json.loads((settings.model_dir / "diabetes.json").read_text())
    metadata["features"] = ["unsupported"]
    (tmp_path / "diabetes.json").write_text(json.dumps(metadata))
    settings.model_dir = tmp_path
    with pytest.raises(ValueError, match="Incompatible"):
        ModelStore(settings)
