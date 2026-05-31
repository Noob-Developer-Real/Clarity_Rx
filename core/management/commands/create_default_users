import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = 'Creates default admin and test user from environment variables'

    def handle(self, *args, **kwargs):
        User = get_user_model()

        # ── Superuser ─────────────────────────────────────────────────────────
        admin_username = os.environ.get('ADMIN_USERNAME', '')
        admin_password = os.environ.get('ADMIN_PASSWORD', '')
        admin_email    = os.environ.get('ADMIN_EMAIL', '')

        if admin_username and admin_password:
            if not User.objects.filter(username=admin_username).exists():
                User.objects.create_superuser(
                    username=admin_username,
                    email=admin_email,
                    password=admin_password,
                )
                self.stdout.write(self.style.SUCCESS(f'Superuser "{admin_username}" created'))
            else:
                self.stdout.write(f'Superuser "{admin_username}" already exists — skipped')
        else:
            self.stdout.write(self.style.WARNING('ADMIN_USERNAME or ADMIN_PASSWORD not set — skipping'))