# Generated manually for Phase 1 local invoice management.
import billing.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Client",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("client_name", models.CharField(max_length=150)),
                ("address", models.TextField()),
                ("country", models.CharField(max_length=80)),
                ("state", models.CharField(max_length=80)),
                ("city", models.CharField(max_length=80)),
                ("pin_code", models.CharField(max_length=12)),
                ("gstin", models.CharField(blank=True, max_length=15)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["client_name"],
            },
        ),
        migrations.CreateModel(
            name="Company",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("company_name", models.CharField(max_length=150)),
                ("address", models.TextField()),
                ("country", models.CharField(max_length=80)),
                ("state", models.CharField(max_length=80)),
                ("city", models.CharField(max_length=80)),
                ("pin_code", models.CharField(max_length=12)),
                ("gstin", models.CharField(blank=True, max_length=15)),
                (
                    "logo",
                    models.FileField(
                        blank=True,
                        upload_to="company_logos/",
                        validators=[billing.validators.validate_logo_file],
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["company_name"],
            },
        ),
    ]
