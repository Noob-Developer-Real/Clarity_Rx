"""
prescription_pipeline.py
========================
Full pipeline with 3-layer drug verification:

  Layer 1 — Gemini OCR  (exact character transcription)
  Layer 2a — LLM Resolver  (garbled OCR → likely Indian brand/generic)
  Layer 2b — medicine_match  (fuzzy DB lookup, now fed resolved names)
  Layer 2c — LLM Validator  (clinical plausibility check on matches)
  Layer 3  — Re-match loop  (re-run medicine_match on LLM override suggestions)
  Layer 4  — describe_drugs  (Groq one-liner descriptions)
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import re
from .ocr_gemini import extract_text_from_image
from medicine.medicine_match import match_drugs
from .groq_simplifier import describe_drugs
from .drug_name_resolver import resolve_drug_names, validate_matches

# ── Minimum score to count as VERIFIED ───────────────────────────────────────
# Original code used whatever medicine_match set. We raise the floor here.
VERIFIED_SCORE_THRESHOLD = 75.0


# ─────────────────────────────────────────────────────────────────────────────
# OCR parsing helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_header_field(ocr_text: str, field: str) -> str:
    """Extract a single header field value from OCR output."""
    pattern = rf"^\s*{re.escape(field)}:\s*(.+)$"
    m = re.search(pattern, ocr_text, re.MULTILINE | re.IGNORECASE)
    return m.group(1).strip() if m else "UNCLEAR"


def _parse_patient_context(ocr_text: str) -> dict:
    """Pull age, weight, complaint from the OCR text for use by the LLM layers."""
    return {
        "age":      _parse_header_field(ocr_text, "Age"),
        "weight":   _parse_header_field(ocr_text, "Weight"),
        "complaint": _parse_header_field(ocr_text, "CHIEF_COMPLAINT"),
    }


def _parse_medications(ocr_text: str) -> list[dict]:
    match = re.search(
        r"MEDICATIONS:\s*(.*?)(?=\n[A-Z_]+:|\Z)",
        ocr_text,
        re.DOTALL,
    )
    if not match:
        return []

    medications_block = match.group(1)
    drugs = []
    current: dict = {}

    for line in medications_block.splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith("DRUG:"):
            if current.get("name"):
                drugs.append(current)
            current = {"name": line.replace("DRUG:", "").strip()}
        elif line.startswith("Form:"):
            current["form"] = line.replace("Form:", "").strip()
        elif line.startswith("Frequency:"):
            current["frequency"] = line.replace("Frequency:", "").strip()
        elif line.startswith("Duration:"):
            current["duration"] = line.replace("Duration:", "").strip()
        elif line.startswith("Instructions:"):
            current["instructions"] = line.replace("Instructions:", "").strip()

    if current.get("name"):
        drugs.append(current)

    return drugs


# ─────────────────────────────────────────────────────────────────────────────
# Score threshold enforcement
# ─────────────────────────────────────────────────────────────────────────────

def _enforce_score_threshold(drugs: list[dict]) -> list[dict]:
    """
    Demote any drug whose match_score is below VERIFIED_SCORE_THRESHOLD.
    medicine_match may mark something VERIFIED at score 60 — we don't allow that.
    """
    for drug in drugs:
        score = float(drug.get("match_score", 0))
        if score < VERIFIED_SCORE_THRESHOLD and drug.get("is_verified"):
            drug["is_verified"] = False
            drug["status"]      = "unverified"
            drug["demotion_reason"] = f"Score {score:.1f} below threshold {VERIFIED_SCORE_THRESHOLD}"
    return drugs


# ─────────────────────────────────────────────────────────────────────────────
# Re-match loop for implausible / overridden drugs
# ─────────────────────────────────────────────────────────────────────────────

def _rematch_overrides(drugs: list[dict]) -> list[dict]:
    """
    For drugs where the LLM validator suggested an override_name,
    create a temporary drug entry with that name and re-run medicine_match.
    If the new match is better, adopt it.
    """
    needs_rematch = [
        (i, d) for i, d in enumerate(drugs)
        if d.get("override_name") and not d.get("is_verified")
    ]

    if not needs_rematch:
        return drugs

    # Build temp list with override names
    temp_drugs = []
    index_map  = []  # maps temp_drugs index → original drugs index

    for orig_i, drug in needs_rematch:
        temp = {
            "name": drug["override_name"],
            "form": drug.get("form", ""),
        }
        temp_drugs.append(temp)
        index_map.append(orig_i)

    # Re-run the matcher
    try:
        rematched = match_drugs(temp_drugs)
    except Exception:
        return drugs

    for temp_i, orig_i in enumerate(index_map):
        r = rematched[temp_i]
        new_score = float(r.get("match_score", 0))
        old_score = float(drugs[orig_i].get("match_score", 0))

        if new_score >= VERIFIED_SCORE_THRESHOLD and new_score > old_score:
            # Adopt the better match, but keep original OCR name
            drugs[orig_i]["matched_name"]    = r.get("matched_name")
            drugs[orig_i]["match_score"]     = new_score
            drugs[orig_i]["is_verified"]     = r.get("is_verified", False)
            drugs[orig_i]["status"]          = r.get("status", "unverified")
            drugs[orig_i]["rematch_applied"] = True
            drugs[orig_i]["rematch_from"]    = drug["override_name"]

    return drugs


# ─────────────────────────────────────────────────────────────────────────────
# Also try matching on resolved_brand / resolved_generic before medicine_match
# ─────────────────────────────────────────────────────────────────────────────

def _inject_resolved_names(drugs: list[dict]) -> list[dict]:
    """
    If the LLM resolver gave a high-confidence resolved_brand, use that as
    the name fed to medicine_match instead of the raw OCR name.
    The original OCR name is preserved in ocr_name.
    """
    for drug in drugs:
        drug["ocr_name"] = drug["name"]  # always preserve original

        conf   = drug.get("resolve_confidence", "low")
        brand  = drug.get("resolved_brand")
        generic = drug.get("resolved_generic")

        if conf in ("high", "medium") and brand:
            drug["name"] = brand
        elif conf == "high" and generic:
            drug["name"] = generic
        # low confidence → leave name as OCR'd
    return drugs


# ─────────────────────────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────────────────────────

def process_prescription(image_url: str) -> dict:
    # ── Layer 1: OCR ─────────────────────────────────────────────────────────
    ocr_text = extract_text_from_image(image_url)
    if not ocr_text:
        return {"success": False, "error": "OCR returned empty result", "drugs": []}

    drugs = _parse_medications(ocr_text)
    if not drugs:
        return {
            "success": False,
            "error": "No medications found in OCR output",
            "drugs": [],
            "raw_ocr": ocr_text,
        }

    # Parse patient context for the LLM layers
    patient_context = _parse_patient_context(ocr_text)

    # ── Layer 2a: LLM Resolver — garbled OCR → Indian brand/generic ──────────
    drugs = resolve_drug_names(drugs, patient_context)

    # Inject resolved names so medicine_match gets cleaner input
    drugs = _inject_resolved_names(drugs)

    # ── Layer 2b: medicine_match fuzzy DB lookup ──────────────────────────────
    drugs = match_drugs(drugs)

    # Enforce our own score threshold (stricter than medicine_match default)
    drugs = _enforce_score_threshold(drugs)

    # ── Layer 2c: LLM clinical plausibility validator ─────────────────────────
    drugs = validate_matches(drugs, patient_context)

    # ── Layer 3: Re-match on LLM override suggestions ─────────────────────────
    drugs = _rematch_overrides(drugs)

    # ── Layer 4: Friendly descriptions ───────────────────────────────────────
    drugs = describe_drugs(drugs)

    return {"success": True, "drugs": drugs, "raw_ocr": ocr_text}