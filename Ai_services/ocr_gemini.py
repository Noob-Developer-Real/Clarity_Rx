import base64
import requests
from django.conf import settings
from google import genai
from google.genai import types

OCR_PROMPT = """\
You are a medical prescription transcription engine for Indian handwritten prescriptions.

━━━ RULE #1 — TRANSCRIBE EXACTLY, NEVER GUESS DRUG NAMES ━━━
Copy drug names character-by-character as written.
If a drug looks like "Mottcare" write "Mottcare" — NOT "Montair".
If a drug looks like "Beonyle" write "Beonyle" — NOT "Benadryl".
Mark illegible characters with (?), e.g. "Mon(?)care".
A wrong drug name is dangerous. Accuracy beats recognisability.

━━━ RULE #2 — BE DETERMINISTIC ━━━
Run this prompt multiple times on the same image → output MUST be identical.
Do not paraphrase, summarise, or reorder anything.
Copy header fields verbatim — same punctuation, same capitalisation every time.
If a field is partially legible, write exactly what you can see + (?) for unclear parts.
Never write UNCLEAR if ANY characters are visible.

━━━ RULE #3 — CHIEF_COMPLAINT: INFER IF NOT WRITTEN ━━━
Doctors often omit the diagnosis. If not explicitly written:
1. Look at the medicines prescribed — what condition do they treat together?
2. Look at any vitals, notes, or shorthand (e.g. "URTI", "fever/cold", "DM2").
3. Make a clinical inference and write it as: "Inferred: <condition> (based on medications)"
Only write UNCLEAR if you genuinely cannot infer anything from the entire prescription.

━━━ SCRIPT & FORMAT RULES ━━━
- Devanagari script: romanise phonetically AND keep original. Format: "subah [सुबह]"
- Common Hindi words: सुबह=morning, शाम=evening, रात=night, खाने के बाद=after food
- Tab./T. = Tablet, Syr./Syp. = Syrup, Cap. = Capsule, Inj. = Injection
- DS = Double Strength, OD = once daily, BD = twice daily, TDS = three times daily
- Frequency notation: 1-0-1 = morning+night, 1-1-1 = TDS, 0-0-1 = night only
- Circled numbers ①②⑤⑦⑩ = duration in days. Write as "<n> days"
- Decode AND keep notation: "1-0-1 (morning + night)"

━━━ OUTPUT FORMAT — copy exactly, no extra text ━━━

HEADER:
  Doctor: <verbatim>
  Qualifications: <verbatim or UNCLEAR>
  Clinic: <verbatim or UNCLEAR>
  Address: <verbatim or UNCLEAR>
  Phone: <verbatim or UNCLEAR>
  Date: <verbatim or UNCLEAR>
  Patient: <verbatim or UNCLEAR>
  Age: <verbatim or UNCLEAR>
  Sex: <M/F or UNCLEAR>
  Weight: <verbatim or UNCLEAR>

VITALS:
  BP: <verbatim or UNCLEAR>
  Pulse: <verbatim or UNCLEAR>
  Temperature: <verbatim or UNCLEAR>
  SpO2: <verbatim or UNCLEAR>

CHIEF_COMPLAINT:
  <verbatim text OR "Inferred: <condition> (based on medications)" — never UNCLEAR if medicines are visible>

INVESTIGATIONS:
  <verbatim or NONE>

MEDICATIONS:
  DRUG: <EXACT characters as written — no corrections>
    Form: <Tablet/Syrup/Capsule/Injection/Drops/Sachet>
    Frequency: <notation + decoded>
    Duration: <n days or UNCLEAR>
    Instructions: <verbatim including Hindi romanised or UNCLEAR>

NOTES:
  <verbatim remaining text or NONE>
"""


def _make_client() -> genai.Client:
    return genai.Client(api_key=settings.GEMINI_API_KEY)


def extract_text_from_image(image_url: str) -> str:
    image_response = requests.get(image_url, timeout=30)
    image_response.raise_for_status()

    mime_type = (
        image_response.headers.get("Content-Type", "image/jpeg")
        .split(";")[0].strip()
    )

    image_part = types.Part(
        inline_data=types.Blob(
            data=base64.b64encode(image_response.content).decode("utf-8"),
            mime_type=mime_type,
        )
    )
    text_part = types.Part(text=OCR_PROMPT)

    client = _make_client()
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[types.Content(parts=[image_part, text_part])],
        config=types.GenerateContentConfig(
            temperature=0.0,          # fully deterministic
            max_output_tokens=4000,
            thinking_config=types.ThinkingConfig(
                thinking_budget=4096,
            ),
        ),
    )

    return response.text.strip() if response.text else ""