import csv
import io
import json
import re
import subprocess
import sys
import warnings
from pathlib import Path
from xml.sax.saxutils import escape

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.catalog import DISCLAIMER, DISEASES, validate_features
from app.config import ROOT

MAX_UPLOAD = 2 * 1024 * 1024


def extract_report(filename, data, disease):
    if Path(filename or "").suffix.lower() != ".pdf":
        return extract_fields(filename, data, disease)
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "app.extract_worker", disease],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=ROOT,
            timeout=8,
            check=False,
        )
        if completed.returncode != 0:
            raise ValueError("PDF could not be processed within resource limits; use TXT or CSV")
        payload = json.loads(completed.stdout)
        if "error" in payload:
            raise ValueError(payload["error"])
        return payload["result"]
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError) as exc:
        raise ValueError("PDF processing failed or timed out; use TXT or CSV") from exc


def extract_fields(filename, data, disease):
    extension = Path(filename or "").suffix.lower()
    if not data or len(data) > MAX_UPLOAD:
        raise ValueError("Upload a nonempty file up to 2 MB")
    if extension not in {".txt", ".csv", ".pdf"}:
        raise ValueError("Supported formats: UTF-8 TXT, CSV, and text-based PDF")
    if extension == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise ValueError("Not a PDF")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                reader = PdfReader(io.BytesIO(data))
                if reader.is_encrypted or len(reader.pages) > 10:
                    raise ValueError("PDF must be unencrypted and at most 10 pages")
                texts = []
                for page in reader.pages:
                    if (
                        len(page.get_contents().get_data() if page.get_contents() else b"")
                        > 2_000_000
                    ):
                        raise ValueError("PDF page is too complex")
                    texts.append(page.extract_text() or "")
                text = "\n".join(texts)
        except Exception as exc:
            raise ValueError("Could not read PDF; use a simple text report instead") from exc
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("TXT and CSV must use UTF-8 encoding") from exc
    if not text.strip() or len(text) > 50000:
        raise ValueError(
            "Report has no extractable text or exceeds 50,000 characters; OCR is not supported"
        )
    spec = DISEASES[disease]["features"]
    found = {}
    if extension == ".csv":
        rows = list(csv.DictReader(io.StringIO(text)))
        if len(rows) != 1 or not set(rows[0]).issubset(spec):
            raise ValueError("CSV must have one row with canonical feature names as column headers")
        for key, value in rows[0].items():
            if value and value.strip():
                found[key] = float(value)
    else:
        for key in spec:
            matches = re.findall(rf"(?im)^\s*{re.escape(key)}\s*[:=]\s*(-?\d+(?:\.\d+)?)\s*$", text)
            if len(matches) > 1:
                raise ValueError(f"Ambiguous duplicate measurement: {key}")
            if matches:
                found[key] = float(matches[0])
    if not found:
        raise ValueError(
            "No canonical fields found. Use key: number lines without units, in the documented units."
        )
    for key, value in found.items():
        if not spec[key][2] <= value <= spec[key][3] or (
            key == "exercise_angina" and value not in (0, 1)
        ):
            raise ValueError(f"Invalid measurement: {key}")
    if len(found) == len(spec):
        validate_features(disease, found)
    return {
        "features": found,
        "missing": [key for key in spec if key not in found],
        "warning": "Draft only: confirm every value, unit, fasting status and measurement date before assessment. No unit conversion is performed. The original file is not stored.",
    }


def make_pdf(assessment):
    output = io.BytesIO()
    styles = getSampleStyleSheet()
    styles["BodyText"].textColor = colors.HexColor("#183143")
    story = []

    def paragraph(text, style="BodyText"):
        story.append(Paragraph(escape(str(text)), styles[style]))
        story.append(Spacer(1, 9))

    paragraph("HealthLens - Educational Research Report", "Title")
    paragraph(DISCLAIMER)
    paragraph("Assessment: " + assessment["id"])
    paragraph("Created (UTC): " + assessment["created"])
    result = assessment["result"]
    paragraph(DISEASES[result["disease"]]["name"], "Heading2")
    paragraph(
        f"Model: {result['model_source']} / {result['model_version']}; not clinically validated"
    )
    paragraph(
        f"Model score: {result['model_score']:.4f}; class: {result['predicted_class']}; threshold: 0.5"
    )
    paragraph("This is an experimental classifier output, not a probability of having disease.")
    paragraph("Confirmed inputs", "Heading2")
    for key, value in result["features"].items():
        spec = DISEASES[result["disease"]]["features"][key]
        paragraph(f"{spec[0]}: {value:g} {spec[1]}")
    paragraph("Reviewed educational information", "Heading2")
    for source in assessment["guidance"]:
        paragraph(source["text"])
        paragraph(source["title"] + " - " + source["url"])
    paragraph(
        "Arrange professional review of symptoms and results. Do not change treatment based on this report."
    )
    SimpleDocTemplate(output, title="HealthLens research report", author="HealthLens").build(story)
    return output.getvalue()
