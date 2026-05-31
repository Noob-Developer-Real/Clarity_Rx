"""
drug_name_resolver.py
=====================
Layer-2 verification: takes OCR-extracted drug names (which may be phonetically
garbled, romanised Hindi, or abbreviated Indian brand names) and uses an LLM to
propose canonical Indian brand / generic names before running medicine_match.

This runs BEFORE medicine_match so the matcher gets clean input.
It also runs AFTER medicine_match to validate that the matched drug makes
clinical sense given the patient context (age, form, other drugs).
"""

import json
import re
from openai import OpenAI
from django.conf import settings


def _make_client() -> OpenAI:
    return OpenAI(
        api_key=settings.GROQ_API_TOKEN,
        base_url="https://api.groq.com/openai/v1",
    )


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Resolve garbled OCR names into likely Indian brand/generic names
# ─────────────────────────────────────────────────────────────────────────────

_RESOLVE_SYSTEM = """\
You are a senior Indian clinical pharmacist with 20 years of experience.
You specialise in identifying Indian brand-name medicines from garbled, misspelt,
or phonetically transcribed text — common when prescriptions are handwritten in
Hindi/regional script and OCR'd into Roman characters.

Your task: given a garbled drug name + contextual clues, return the most likely
REAL Indian brand name(s) and their generic (INN) name.

Rules:
- Think about Indian brand names first (not US/UK brands).
- Use form, frequency, patient age/weight, and co-prescribed drugs as clues.
- Return ONLY valid JSON — no markdown, no explanation.
"""

_RESOLVE_USER_TMPL = """\
OCR prescription context:
  Patient age : {age}
  Patient weight: {weight}
  All drugs on prescription (raw OCR names): {all_drugs}

For each drug below, suggest the most likely real Indian brand name and generic name.

Drugs to resolve:
{drug_list}

Return a JSON array (same order). Each element:
{{
  "ocr_name": "<original garbled name>",
  "resolved_brand": "<most likely Indian brand name, or null if unsure>",
  "resolved_generic": "<INN / generic name, or null if unsure>",
  "confidence": "high" | "medium" | "low",
  "reasoning": "<one short sentence>"
}}
"""


def resolve_drug_names(drugs: list[dict], patient_context: dict) -> list[dict]:
    """
    Enriches each drug dict with:
      resolved_brand    – best-guess Indian brand name
      resolved_generic  – INN generic name
      resolve_confidence – high / medium / low

    Falls back gracefully if the API call fails.
    """
    if not drugs:
        return drugs

    age    = patient_context.get("age", "unknown")
    weight = patient_context.get("weight", "unknown")
    all_names = [d.get("name", "") for d in drugs]

    drug_list_lines = "\n".join(
        f'{i+1}. OCR name: "{d.get("name","")}"'
        f'  |  Form: {d.get("form","unknown")}'
        f'  |  Frequency: {d.get("frequency","unknown")}'
        f'  |  Duration: {d.get("duration","unknown")}'
        for i, d in enumerate(drugs)
    )

    prompt = _RESOLVE_USER_TMPL.format(
        age=age,
        weight=weight,
        all_drugs=", ".join(f'"{n}"' for n in all_names),
        drug_list=drug_list_lines,
    )

    try:
        client = _make_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": _RESOLVE_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.1,
            max_tokens=max(600, len(drugs) * 150),
        )

        raw = response.choices[0].message.content.strip()
        # Strip any accidental markdown fences
        raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`")

        resolutions = json.loads(raw)

        for i, drug in enumerate(drugs):
            if i >= len(resolutions):
                break
            r = resolutions[i]
            drug["resolved_brand"]     = r.get("resolved_brand")
            drug["resolved_generic"]   = r.get("resolved_generic")
            drug["resolve_confidence"] = r.get("confidence", "low")
            drug["resolve_reasoning"]  = r.get("reasoning", "")

    except Exception as e:
        # Non-fatal — pipeline continues without resolution hints
        for drug in drugs:
            drug.setdefault("resolved_brand",     None)
            drug.setdefault("resolved_generic",   None)
            drug.setdefault("resolve_confidence", "low")
            drug.setdefault("resolve_reasoning",  f"resolver error: {e}")

    return drugs


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Post-match clinical plausibility check
# ─────────────────────────────────────────────────────────────────────────────

_VALIDATE_SYSTEM = """\
You are a senior Indian clinical pharmacist.
You will receive a list of matched drugs (OCR name → database match) and patient
context. For each match, decide if it is clinically plausible.

Return ONLY valid JSON — no markdown, no explanation.
"""

_VALIDATE_USER_TMPL = """\
Patient context:
  Age    : {age}
  Weight : {weight}
  Chief complaint / diagnosis: {complaint}

Matched drugs (evaluate each):
{drug_list}

For each drug return:
{{
  "index": <0-based int>,
  "ocr_name": "<original>",
  "matched_name": "<what the DB returned>",
  "plausible": true | false,
  "override_name": "<better Indian brand/generic if not plausible, else null>",
  "reason": "<one sentence>"
}}

Return a JSON array.
"""


def validate_matches(drugs: list[dict], patient_context: dict) -> list[dict]:
    """
    Post-match validation. If a match is implausible, sets:
      match_plausible = False
      plausibility_reason = <why>
      override_name = <LLM suggestion for re-matching>
    and demotes is_verified to False.
    """
    if not drugs:
        return drugs

    age       = patient_context.get("age", "unknown")
    weight    = patient_context.get("weight", "unknown")
    complaint = patient_context.get("complaint", "unknown")

    drug_list_lines = "\n".join(
        f'{i}. OCR="{d.get("name","")}"'
        f'  matched="{d.get("matched_name") or "no match"}"'
        f'  score={d.get("match_score",0)}'
        f'  form={d.get("form","?")}'
        f'  resolved_brand="{d.get("resolved_brand") or "?"}"'
        f'  resolved_generic="{d.get("resolved_generic") or "?"}"'
        f'  resolve_confidence={d.get("resolve_confidence","low")}'
        for i, d in enumerate(drugs)
    )

    prompt = _VALIDATE_USER_TMPL.format(
        age=age,
        weight=weight,
        complaint=complaint,
        drug_list=drug_list_lines,
    )

    try:
        client = _make_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": _VALIDATE_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.1,
            max_tokens=max(600, len(drugs) * 150),
        )

        raw = response.choices[0].message.content.strip()
        raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`")

        validations = json.loads(raw)
        val_map = {v["index"]: v for v in validations}

        for i, drug in enumerate(drugs):
            v = val_map.get(i, {})
            plausible = v.get("plausible", True)
            drug["match_plausible"]    = plausible
            drug["plausibility_reason"] = v.get("reason", "")
            drug["override_name"]      = v.get("override_name")

            # Demote to unverified if implausible
            if not plausible:
                drug["is_verified"] = False
                drug["status"]      = "unverified"

    except Exception as e:
        for drug in drugs:
            drug.setdefault("match_plausible",    True)
            drug.setdefault("plausibility_reason", f"validator error: {e}")
            drug.setdefault("override_name",       None)

    return drugs