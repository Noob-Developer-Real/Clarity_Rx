<div align="center">

<img src="images/favicon.jpg" width="80" alt="ClarityRx Logo" />

# ClarityRx

### AI-Powered Indian Prescription Reader & Medicine Price Comparator

*Upload a handwritten prescription. Understand every medicine. Find the best price.*

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Django](https://img.shields.io/badge/Django-4.x-092E20?style=for-the-badge&logo=django&logoColor=white)](https://djangoproject.com)
[![Gemini](https://img.shields.io/badge/Gemini_2.5_Flash-OCR-4285F4?style=for-the-badge&logo=google&logoColor=white)](https://deepmind.google/gemini)
[![Groq](https://img.shields.io/badge/Groq-LLaMA_3.3_70B-F55036?style=for-the-badge)](https://groq.com)

**Built for · HackIndia / Hackathon 2026**

</div>

---

## The Problem

In India, over **1 billion prescriptions** are written every year — most of them by hand, in a mix of English brand names, Hindi instructions, and shorthand that even pharmacists struggle to read. Patients often:

- Cannot read their own prescription
- Don't know what a medicine is for or when to take it
- Overpay because they don't know cheaper alternatives exist
- Miss critical dosage instructions written in regional script

**ClarityRx solves all four problems in one upload.**

---

## What ClarityRx Does

```
Upload prescription image
         │
         ▼
  Gemini 2.5 Flash OCR  ──────────────────►  Exact transcription
         │                                    Hindi/Devanagari aware
         ▼
  LLM Drug Name Resolver ─────────────────►  "Sinarest" ← "Sinarset"
         │                                    Indian brand knowledge
         ▼
  Fuzzy Medicine Matcher ─────────────────►  Verified against 20k+
         │                                    Indian medicine records
         ▼
  Clinical Plausibility Check ────────────►  Does this make sense
         │                                    for this patient?
         ▼
  Patient-Friendly Summary ───────────────►  "You likely have a
         │                                    respiratory infection…"
         ▼
  Live Price Comparison ──────────────────►  Truemeds ₹27 ← BEST
  (triggered on demand)                      Netmeds  ₹28.5
                                             Tata 1mg ₹29
```

---

## Key Features

| Feature | Description |
|---|---|
| 🔬 **Multi-layer Drug Verification** | 5-step pipeline from raw OCR to clinically validated match |
| 🗣️ **Hindi-Aware OCR** | Understands Devanagari script, MAN notation, circled durations |
| 🧠 **AI Health Summary** | Explains your condition and medicines in plain language |
| 💰 **Live Price Comparison** | Real-time prices from Truemeds, Netmeds, Tata 1mg — side by side |
| 📊 **Confidence Scores** | Every drug shows how confident the AI is in its identification |
| ⚡ **Parallel Price Fetching** | All 3 pharmacies queried simultaneously — results in ~10–20 seconds |
| 🔒 **Privacy First** | User-scoped data — patients only see their own prescriptions |

---

## Demo

> Upload → Analyse → Compare → Save

**Input:** Photo of a handwritten prescription (even messy ones)

**Output:**
- Patient condition banner (Chief Complaint + Age + Weight)
- Medicine catalog — 3-column grid, one card per drug
  - Verified badge + confidence bar
  - Form, frequency, duration chips
  - Plain-English description
  - "Compare Prices" button → live catalog from 3 pharmacies
- AI health summary paragraph at the bottom

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Django Backend                          │
│                                                                 │
│  views.py                                                       │
│  ├── upload_prescription()   ← runs full pipeline on upload     │
│  ├── view_prescription()     ← renders result page              │
│  └── api_medicine_prices()   ← lazy price fetch on button click │
│                                                                 │
│  Ai_services/                                                   │
│  ├── prescription_pipeline.py   ← orchestrates all AI layers   │
│  ├── ocr_gemini.py              ← Google Gemini 2.5 Flash       │
│  ├── drug_name_resolver.py      ← Groq LLaMA 3.3 70B           │
│  └── groq_simplifier.py         ← Groq LLaMA 3.3 70B           │
│                                                                 │
│  medicine/                                                      │
│  ├── medicine_match.py          ← RapidFuzz local matcher       │
│  ├── medicine_loader.py         ← JSON database loader          │
│  └── indian_medicine_data.json  ← 20k+ Indian medicine records  │
│                                                                 │
│  services/                                                      │
│  └── medicine_price_services.py ← Anakin Wire → 3 pharmacies   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Pipeline Deep Dive

### Layer 1 — Gemini OCR
`gemini-2.5-flash` with extended thinking (`thinking_budget=4096`) transcribes every character exactly as written. It understands Indian prescription conventions:
- Hindi/Devanagari mixed with English brand names
- `1-0-1` frequency notation (Morning-Afternoon-Night)
- Circled numbers ①⑦⑩ = duration in days
- Common prefixes: `Tab.`, `Syr.`, `Cap.`, `Inj.`

### Layer 2a — LLM Drug Name Resolver
`llama-3.3-70b-versatile` on Groq takes garbled OCR names and suggests the most likely real Indian brand or generic name, using patient age, weight, and co-medications as context clues.

### Layer 2b — Fuzzy Medicine Matcher
`rapidfuzz.partial_ratio` against a 20k+ local JSON database of Indian medicines. Prefix pre-filtering for speed. Threshold: 75/100 to be marked verified.

### Layer 2c — Clinical Plausibility Validator
A second LLM call checks whether each matched drug makes clinical sense for this patient's condition, age, and other medications. Implausible matches are flagged and sent for re-matching.

### Layer 3 — Re-match Loop
Drugs flagged as implausible are re-run through the fuzzy matcher using the LLM's suggested correction. Better matches are adopted automatically.

### Layer 4 — Patient Descriptions + Health Summary
Single Groq batch call generates one-sentence plain-English descriptions per drug. A separate call synthesises a 3–5 sentence health summary explaining the likely condition.

### Price Layer — On-Demand, Parallel
Triggered only when user clicks "Compare Prices". Three Anakin Wire async jobs (`tm_search`, `nm_search`, `tmg_search`) submit simultaneously via `ThreadPoolExecutor`, results merged and sorted cheapest-first.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web Framework | Django 4.x |
| OCR | Google Gemini 2.5 Flash |
| LLM | Groq — LLaMA 3.3 70B Versatile |
| Fuzzy Matching | RapidFuzz |
| Medicine Database | Custom Indian Medicine JSON (20k+ records) |
| Price APIs | Anakin Wire (Truemeds · Netmeds · Tata 1mg) |
| Frontend | Django Templates · Tailwind CSS CDN · Font Awesome |
| Database | SQLite (dev) · PostgreSQL (prod) |
| Language | Python 3.11+ |

---

## Installation

```bash
# Clone
git clone https://github.com/Noob-Developer-Real/ClarityRx.git
cd ClarityRx

# Virtual environment
python -m venv .venv
source .venv/bin/activate

# Install
pip install -r requirements.txt

# Configure
cp .env.example .env
# Add your API keys (see Environment Variables below)

# Database
python manage.py makemigrations
python manage.py migrate

# Run
python manage.py runserver
```

---

## Environment Variables

```env
SECRET_KEY=your-django-secret-key
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost

GEMINI_API_KEY=your-gemini-api-key
GROQ_API_TOKEN=your-groq-api-key
ANAKIN_API_KEY=ask_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Optional — affects Tata 1mg delivery ETA
MEDICINE_PRICE_CITY=New Delhi
```

---

## Team

Built with ❤️ by **Noob Mon** — solo project for HackIndia 2026.

---

## License

MIT — free to use, modify, and distribute.
