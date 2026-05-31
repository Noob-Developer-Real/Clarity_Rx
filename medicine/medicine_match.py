from medicine.medicine_loader import load_medicine_names
from rapidfuzz import process, fuzz

# ── Load once at import time — never reload per request ──────────────────────
MEDICINE_LIST = load_medicine_names()
print(f"[medicine_match] Loaded {len(MEDICINE_LIST)} medicines")

VERIFIED_THRESHOLD = 75


def _fuzzy_match(name: str) -> tuple[str | None, float]:
    """
    Return (best_matched_name, score) for *name* against the local dataset.
    Uses prefix pre-filter for speed, falls back to full list if needed.
    """
    name = name.lower().strip()
    if not name:
        return None, 0.0

    # Pre-filter by first 2 chars — massively reduces search space
    prefix = name[:2]
    candidates = [m for m in MEDICINE_LIST if m.startswith(prefix)]
    if len(candidates) < 10:
        candidates = MEDICINE_LIST

    results = process.extract(
        name,
        candidates,
        scorer=fuzz.partial_ratio,
        limit=1,
    )

    if not results:
        return None, 0.0

    matched, score, _ = results[0]

    # Small boost if first 3 chars match exactly
    if len(matched) >= 3 and len(name) >= 3 and matched[:3] == name[:3]:
        score = min(100.0, score + 8)

    return matched, round(score, 2)


def match_drugs(drugs: list[dict]) -> list[dict]:
    """
    Run every drug through local fuzzy match.

    Input:
        [{"name": "Sinarest", "form": "Tablet", "frequency": "...", ...}, ...]

    Added fields per drug:
        matched_name   — best local match (or None)
        match_score    — 0-100
        is_verified    — True if score >= 75
        status         — "verified" | "unverified"
    """
    for drug in drugs:
        name = drug.get("name", "")
        matched, score = _fuzzy_match(name)

        drug["matched_name"] = matched
        drug["match_score"] = score
        drug["is_verified"] = score >= VERIFIED_THRESHOLD
        drug["status"] = "verified" if score >= VERIFIED_THRESHOLD else "unverified"

    return drugs