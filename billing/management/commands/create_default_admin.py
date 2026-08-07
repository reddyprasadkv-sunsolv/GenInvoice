from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create the local-only default admin user."

    def handle(self, *args, **options):
        username = "admin"
        password = "Admin@12345"
        email = ""
        User = get_user_model()

        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": email,
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
            },
        )

        if created:
            user.set_password(password)
            user.save()
            self.stdout.write(self.style.SUCCESS("Default local admin user created: admin"))
        else:
            changed_fields = []
            if email and not user.email:
                user.email = email
                changed_fields.append("email")
            if not user.is_staff:
                user.is_staff = True
                changed_fields.append("is_staff")
            if not user.is_superuser:
                user.is_superuser = True
                changed_fields.append("is_superuser")
            if not user.is_active:
                user.is_active = True
                changed_fields.append("is_active")
            if changed_fields:
                user.save(update_fields=changed_fields)
            self.stdout.write(self.style.SUCCESS("Default local admin user already exists. Password was not changed."))
        self.stdout.write(self.style.WARNING("Use this account only for local access."))
