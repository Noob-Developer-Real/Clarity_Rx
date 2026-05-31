from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User

class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Professional Info', {'fields': ('role',)}),
    )
admin.site.register(User, CustomUserAdmin)