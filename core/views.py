import re
import time
import logging
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .models import Prescription, PrescriptionMedicine
from Ai_services.prescription_pipeline import process_prescription
from services.medicine_price_services import MedicinePriceService

logger = logging.getLogger(__name__)

MIN_CONFIDENCE_SCORE = 75


# ─────────────────────────────────────────────────────────────────────────────
# Upload + pipeline
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def upload_prescription(request):
    if request.method != "POST":
        return render(request, "core/upload_form.html")

    image = request.FILES.get("image")
    if not image:
        messages.error(request, "Please upload a prescription image.")
        return redirect("upload_prescription")

    prescription = Prescription.objects.create(
        patient=request.user,
        image=image,
        processing_status="processing",
    )

    start_time = time.time()

    try:
        image_url = request.build_absolute_uri(prescription.image.url)
        result    = process_prescription(image_url)

        if not result.get("success"):
            prescription.processing_status = "failed"
            prescription.error_message     = result.get("error", "Unknown pipeline error")
            prescription.raw_text          = result.get("raw_ocr", "")
            prescription.save()
            return redirect("view_prescription", id=prescription.id)

        drugs   = result.get("drugs", [])
        raw_ocr = result.get("raw_ocr", "")

        # ── Parse patient context from raw OCR ───────────────────────────────
        def _ocr_field(label):
            m = re.search(rf"^\s*{re.escape(label)}:\s*(.+)$", raw_ocr,
                          re.MULTILINE | re.IGNORECASE)
            v = m.group(1).strip() if m else ""
            return "" if v.upper() == "UNCLEAR" else v

        complaint = _ocr_field("CHIEF_COMPLAINT")
        if not complaint:
            # sometimes written inline after the label on one line
            m = re.search(r"CHIEF_COMPLAINT:\s*(.+?)(?:\n[A-Z_]+:|\Z)", raw_ocr, re.DOTALL)
            complaint = m.group(1).strip() if m else ""
            if complaint.upper() == "UNCLEAR":
                complaint = ""

        age    = _ocr_field("Age")
        weight = _ocr_field("Weight")

        # ── Build AI summary via Groq ────────────────────────────────────────
        verified_drugs = [d for d in drugs if d.get("is_verified") and
                          float(d.get("match_score", 0)) >= MIN_CONFIDENCE_SCORE]
        ai_summary = _build_ai_summary_from_drugs(verified_drugs, complaint)

        # ── Persist everything ───────────────────────────────────────────────
        with transaction.atomic():
            prescription.raw_text          = raw_ocr
            prescription.pipeline_result   = result
            prescription.processing_status = "completed"
            prescription.processing_time   = round(time.time() - start_time, 2)
            prescription.diagnosis         = complaint
            prescription.age               = age
            prescription.weight            = weight
            prescription.simplified_text   = ai_summary   # cached here
            prescription.save()

            # Save ALL drugs (verified + unverified) — template decides what to show
            for drug in drugs:
                score = float(drug.get("match_score", 0))
                PrescriptionMedicine.objects.create(
                    prescription     = prescription,
                    ocr_name         = drug.get("ocr_name") or drug.get("name") or "",
                    matched_name     = drug.get("matched_name") or "",
                    resolved_brand   = drug.get("resolved_brand") or "",   # None → ""
                    resolved_generic = drug.get("resolved_generic") or "",
                    match_score      = score,
                    is_verified      = drug.get("is_verified", False),
                    description      = drug.get("description") or "",
                    # cheapest_price / cheapest_source left NULL — filled by lazy price API
                )

        messages.success(request, "Prescription processed successfully.")

    except Exception as e:
        logger.exception("Pipeline error for prescription %s", prescription.id)
        prescription.processing_status = "failed"
        prescription.error_message     = str(e)
        prescription.processing_time   = round(time.time() - start_time, 2)
        prescription.save()
        messages.error(request, "Prescription processing failed.")

    return redirect("view_prescription", id=prescription.id)


# ─────────────────────────────────────────────────────────────────────────────
# Result page
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def view_prescription(request, id):
    prescription = get_object_or_404(Prescription, id=id, patient=request.user)

    # Pull all medicine rows sorted best-match first
    db_medicines = list(prescription.medicines.order_by("-match_score"))

    # Merge form/frequency/duration/instructions from pipeline_result JSON
    # (these fields aren't in the model — we attach them as attributes)
    pipeline_drug_map = {}
    if prescription.pipeline_result:
        for d in prescription.pipeline_result.get("drugs", []):
            key = (d.get("matched_name") or d.get("name", "")).lower().strip()
            pipeline_drug_map[key] = d
            # also index by ocr_name for fallback
            ocr_key = d.get("ocr_name", d.get("name", "")).lower().strip()
            pipeline_drug_map[ocr_key] = d

    for med in db_medicines:
        key  = (med.matched_name or med.ocr_name).lower().strip()
        extra = pipeline_drug_map.get(key, {})
        med.form         = extra.get("form", "")
        med.frequency    = extra.get("frequency", "")
        med.duration     = extra.get("duration", "")
        med.instructions = extra.get("instructions", "")

    verified_medicines   = [m for m in db_medicines
                            if m.is_verified and m.match_score >= MIN_CONFIDENCE_SCORE]
    unverified_medicines = [m for m in db_medicines
                            if not (m.is_verified and m.match_score >= MIN_CONFIDENCE_SCORE)]

    context = {
        "prescription":          prescription,
        "verified_medicines":    verified_medicines,
        "unverified_medicines":  unverified_medicines,
        "verified_count":        len(verified_medicines),
        "total_count":           len(db_medicines),
        "processing_time":       prescription.processing_time,
        # ai_summary is in prescription.simplified_text (saved at upload time)
        "ai_summary":            prescription.simplified_text,
        "chief_complaint":       prescription.diagnosis,
        "patient_age":           prescription.age,
        "patient_weight":        prescription.weight,
    }

    return render(request, "core/result.html", context)   # ← FIXED template name


# ─────────────────────────────────────────────────────────────────────────────
# Lazy price API  —  GET /api/prices/?drug=<name>&medicine_id=<id>
# ─────────────────────────────────────────────────────────────────────────────

@require_GET
@login_required
def api_medicine_prices(request):
    """
    Called by JS when user clicks "Compare Prices".
    No prices are fetched at upload time — this is the only price entry point.

    Returns: { drug_name, sources, cheapest, elapsed_s }
    Caches cheapest_price / cheapest_source on the PrescriptionMedicine row.
    """
    drug_name   = request.GET.get("drug", "").strip()
    medicine_id = request.GET.get("medicine_id", "").strip()

    logger.info("[price_api] HIT drug='%s' medicine_id='%s' user=%s", drug_name, medicine_id, request.user)

    if not drug_name:
        return JsonResponse({"error": "drug parameter required"}, status=400)

    # Ownership check + cache read
    medicine_row = None
    if medicine_id:
        try:
            medicine_row = PrescriptionMedicine.objects.get(
                id=medicine_id,
                prescription__patient=request.user,
            )
            # Return full cached result if already fetched (price_data has the complete shape)
            if medicine_row.price_data:
                logger.info("[price_api] CACHE HIT medicine_id=%s", medicine_id)
                return JsonResponse(medicine_row.price_data)
        except PrescriptionMedicine.DoesNotExist:
            logger.warning("[price_api] medicine_id=%s not found or wrong user", medicine_id)
            return JsonResponse({"error": "Not found"}, status=404)

    # Fetch live prices from all 3 pharmacies (parallel inside service)
    try:
        svc    = MedicinePriceService()
        result = svc.get_prices_for_drug(drug_name)
    except Exception as e:
        logger.error("Price fetch failed for '%s': %s", drug_name, e)
        return JsonResponse(
            {"drug_name": drug_name, "sources": [], "cheapest": None, "error": str(e)},
            status=500,
        )

    # Save cheapest price + source to DB immediately
    cheapest = result.get("cheapest")
    if medicine_row:
        medicine_row.price_data = result

        if cheapest:
            medicine_row.cheapest_price = cheapest.get("price")
            medicine_row.cheapest_source = cheapest.get("source", "")

        medicine_row.save(
            update_fields=[
                "price_data",
                "cheapest_price",
                "cheapest_source"
            ]
        )

    return JsonResponse(result)


# ─────────────────────────────────────────────────────────────────────────────
# History
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def prescription_history(request):
    prescriptions = (
        Prescription.objects
        .filter(patient=request.user)
        .order_by("-created_at")
    )
    return render(request, "core/history.html", {"prescriptions": prescriptions})


# ─────────────────────────────────────────────────────────────────────────────
# Error handlers
# ─────────────────────────────────────────────────────────────────────────────

def error_404(request, exception):
    return render(request, "404.html", status=404)

def error_500(request):
    return render(request, "500.html", status=500)
def health_check(request):
    return HttpResponse("OK", status=200)

# ─────────────────────────────────────────────────────────────────────────────
# Internal: AI health summary (called once at upload, result cached in model)
# ─────────────────────────────────────────────────────────────────────────────

def _build_ai_summary_from_drugs(verified_drugs: list, complaint: str) -> str:
    """
    Groq call — writes a 3-5 sentence patient-friendly health summary.
    Takes the raw drug dicts from the pipeline (not ORM objects).
    Returns "" on any failure — never raises.
    """
    if not verified_drugs:
        return ""

    try:
        from django.conf import settings
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.GROQ_API_TOKEN,
            base_url="https://api.groq.com/openai/v1",
        )

        complaint_text = complaint or "not specified"
        drug_lines = "\n".join(
            f"- {d.get('matched_name') or d.get('name', 'unknown')}"
            f" ({d.get('form', 'unknown form')},"
            f" {d.get('frequency', 'unknown frequency')},"
            f" {d.get('duration', 'unknown duration')})"
            for d in verified_drugs
        )

        prompt = f"""A patient visited a doctor with the complaint: "{complaint_text}".
The doctor prescribed:
{drug_lines}

Write 3-5 sentences, patient-friendly:
1. What health condition the patient likely has
2. What each medicine broadly helps with (no brand names, just purpose)
3. General advice on taking these together

No bullet points. Flowing prose only. Warm and reassuring tone."""

        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system",
                 "content": "You are a friendly pharmacist explaining a prescription to a patient in plain language."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=300,
        )
        return resp.choices[0].message.content.strip()

    except Exception as e:
        logger.warning("AI summary failed: %s", e)
        return ""