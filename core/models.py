from django.db import models
from django.conf import settings
import uuid


class Prescription(models.Model):
    STATUS_CHOICES = [
        ("pending",    "Pending"),
        ("processing", "Processing"),
        ("completed",  "Completed"),
        ("failed",     "Failed"),
    ]

    id                = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient           = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="prescriptions")
    image             = models.ImageField(upload_to="prescriptions/")
    raw_text          = models.TextField(blank=True, default="")
    simplified_text   = models.TextField(blank=True, default="")   # AI health summary cached here
    pipeline_result   = models.JSONField(null=True, blank=True)
    patient_name      = models.CharField(max_length=255, blank=True, default="")
    age               = models.CharField(max_length=50,  blank=True, default="")
    weight            = models.CharField(max_length=50,  blank=True, default="")
    diagnosis         = models.TextField(blank=True, default="")   # chief complaint from OCR
    processing_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    processing_time   = models.FloatField(null=True, blank=True)
    error_message     = models.TextField(blank=True, default="")
    created_at        = models.DateTimeField(auto_now_add=True)
    updated_at        = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.patient} — {self.created_at.date()}"


class PrescriptionMedicine(models.Model):
    prescription     = models.ForeignKey(Prescription, on_delete=models.CASCADE, related_name="medicines")
    ocr_name         = models.CharField(max_length=255, default="")
    matched_name     = models.CharField(max_length=255, blank=True, default="")
    resolved_brand   = models.CharField(max_length=255, blank=True, default="")   # ← was NOT NULL, no default
    resolved_generic = models.CharField(max_length=255, blank=True, default="")   # ← same
    match_score      = models.FloatField(default=0)
    is_verified      = models.BooleanField(default=False)
    description      = models.TextField(blank=True, default="")
    price_data = models.JSONField(
        null=True,
        blank=True
    )

    cheapest_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )

    cheapest_source = models.CharField(
        max_length=100,
        blank=True,
        default=""
    )

    def __str__(self):
        return self.matched_name or self.ocr_name