from django.urls import path
from . import views

urlpatterns = [
path(
"",
views.upload_prescription,
name="upload_prescription"
),
path("api/prices/", views.api_medicine_prices, name="api_medicine_prices"),
path(
    "prescription/<uuid:id>/",
    views.view_prescription,
    name="view_prescription"
),
path("health/", views.health_check, name="health_check"),
path(
    "history/",
    views.prescription_history,
    name="prescription_history"
),


]
