import json
from django.conf import settings
from openai import OpenAI


def _make_client() -> OpenAI:
    return OpenAI(
        api_key=settings.GROQ_API_TOKEN,
        base_url="https://api.groq.com/openai/v1",
    )


def describe_drugs(drugs: list[dict]) -> list[dict]:
    if not drugs:
        return drugs

    verified   = [d for d in drugs if d.get("is_verified")]
    unverified = [d for d in drugs if not d.get("is_verified")]

    for drug in unverified:
        drug["description"] = (
            "Unverified medicine — could not be matched in the local dataset. "
            "Please confirm with a pharmacist before use."
        )

    if not verified:
        return drugs

    drug_lines = "\n".join(
        f"{i + 1}. {d.get('matched_name') or d.get('name')}"
        for i, d in enumerate(verified)
    )

    max_tokens = max(300, len(verified) * 120)

    prompt = f"""For each medicine below, write ONE sentence explaining what it is used for.
Be simple and clear — written for a patient, not a doctor.
Return ONLY a JSON array of strings, same order as input. No markdown, no explanation.

Medicines:
{drug_lines}

Example output for 3 medicines:
["Used to relieve cold and allergy symptoms like runny nose and sneezing.",
 "An antibiotic used to treat bacterial infections.",
 "Used to reduce stomach acid and treat acidity or ulcers."]"""

    try:
        client = _make_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a pharmacist. Return only a JSON array of "
                        "one-sentence medicine descriptions. No markdown, no extra text."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=max_tokens,
        )

        raw = response.choices[0].message.content.strip()
        if "```" in raw:
            raw = raw.split("```")[1].replace("json", "").strip()

        descriptions = json.loads(raw)

        for i, drug in enumerate(verified):
            drug["description"] = (
                descriptions[i] if i < len(descriptions) else "Description unavailable."
            )

    except Exception:
        for drug in verified:
            if "description" not in drug:
                drug["description"] = "Description unavailable."

    return drugs