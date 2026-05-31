from django.contrib import admin
from .models import Prescription,PrescriptionMedicine


admin.site.register(Prescription)
admin.site.register(PrescriptionMedicine)