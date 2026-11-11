from django.core.management.base import BaseCommand

from apps.common.integrations.credential_pdf import generate_encrypted_pdf


class Command(BaseCommand):
    help = "Write sample_credentials.pdf (test data only, for layout checks)."

    def handle(self, *args, **options):
        pdf_bytes = generate_encrypted_pdf(
            company_name="Shesa Architects",
            employee_name="Jane Doe",
            email="jane@shesa.it",
            dsm_username="jane",
            portal_url="https://vpn.shesa.it",
            dsm_passphrase="Password123",
        )
        with open("sample_credentials.pdf", "wb") as f:
            f.write(pdf_bytes)
        self.stdout.write(self.style.SUCCESS("Wrote sample_credentials.pdf (open password: jane@shesa.it)"))
