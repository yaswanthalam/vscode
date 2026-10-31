DISCLAIMER = (
    "Educational research only. This is not a diagnosis, medical advice, or a clinically "
    "validated risk estimate. Synthetic demo scores do not estimate your health risk. "
    "A low score cannot rule out illness. Discuss symptoms and test results with a clinician."
)

# Bounds validate data entry, not diagnostic thresholds.
DISEASES = {
    "diabetes": {
        "name": "Diabetes",
        "features": {
            "age": ("Age", "years", 18, 100),
            "glucose": ("Fasting plasma glucose", "mg/dL", 40, 600),
            "bmi": ("Body mass index", "kg/m2", 12, 65),
            "systolic_bp": ("Systolic blood pressure", "mmHg", 70, 250),
        },
    },
    "heart": {
        "name": "Heart disease",
        "features": {
            "age": ("Age", "years", 18, 100),
            "systolic_bp": ("Resting systolic blood pressure", "mmHg", 70, 250),
            "cholesterol": ("Total cholesterol", "mg/dL", 80, 600),
            "max_heart_rate": ("Maximum exercise heart rate", "bpm", 50, 230),
            "exercise_angina": ("Exercise-induced angina (no=0, yes=1)", "0 or 1", 0, 1),
        },
    },
    "kidney": {
        "name": "Chronic kidney disease",
        "features": {
            "age": ("Age", "years", 18, 100),
            "systolic_bp": ("Systolic blood pressure", "mmHg", 70, 250),
            "creatinine": ("Serum creatinine", "mg/dL", 0.2, 20),
            "blood_urea": ("Blood urea (not BUN)", "mg/dL", 5, 300),
            "hemoglobin": ("Hemoglobin", "g/dL", 3, 22),
        },
    },
}


def public_catalog():
    return [
        {
            "id": key,
            "name": value["name"],
            "features": [
                {"key": k, "label": v[0], "unit": v[1], "min": v[2], "max": v[3]}
                for k, v in value["features"].items()
            ],
        }
        for key, value in DISEASES.items()
    ]


def validate_features(disease, values):
    if disease not in DISEASES:
        raise ValueError("Unsupported disease")
    spec = DISEASES[disease]["features"]
    if set(values) != set(spec):
        raise ValueError("Provide exactly these features: " + ", ".join(spec))
    result = {}
    for key, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key} must be a number")
        if not spec[key][2] <= value <= spec[key][3]:
            raise ValueError(f"{key} must be between {spec[key][2]} and {spec[key][3]}")
        if key == "exercise_angina" and value not in (0, 1):
            raise ValueError("exercise_angina must be 0 or 1")
        result[key] = float(value)
    return result
