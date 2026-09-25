"""
mailer.py - Sends the welcome email with an AES-256 encrypted PDF attachment.

The email body contains NO credentials - only a link to the portal and
instructions. The PDF attachment contains the employee's username and portal
URL, but deliberately NOT the NAS password (which must be communicated
separately - see credential_pdf.py for the design rationale).

Note: The passphrase strategy has been set to default to the recipient's email address.
"""

import io
import os
import re
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import credential_pdf

SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtps.aruba.it")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 465))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "") or SMTP_USER
PORTAL_URL = os.environ.get("PUBLIC_APP_URL", "https://vpn.shesa.it").rstrip("/")
COMPANY_NAME = os.environ.get("COMPANY_NAME", "SHESA S.r.l.")


def send_welcome_email(
    recipient_email: str,
    username: str,
    passphrase: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> None:
    """
    Sends a welcome email with an AES-256 encrypted PDF attachment.

    The email body contains no credentials. The PDF contains the employee's
    username and portal URL (but NOT the NAS password). The PDF is encrypted
    using the recipient's email address by default unless another passphrase is provided.

    Args:
        recipient_email: Where to send the email (also used as the default passphrase).
        username:        Their DSM/NAS username.
        passphrase:      PDF encryption passphrase (defaults to recipient_email).
        first_name:      Used for the email greeting and PDF header.
        last_name:       Used for the PDF header.
    """
    if not SMTP_SERVER or not SMTP_USER or not SMTP_PASSWORD:
        print("[mailer] Warning: SMTP credentials not configured. Skipping email.")
        return

    display_name = first_name or username
    full_name = " ".join(filter(None, [first_name, last_name])) or username

    # Generate the encrypted PDF entirely in memory - never touches disk.
    pdf_bytes = credential_pdf.generate_encrypted_pdf(
        company_name=COMPANY_NAME,
        employee_name=full_name,
        email=recipient_email,
        dsm_username=username,
        dsm_passphrase=passphrase,
        portal_url=PORTAL_URL,
    )

    subject = f"Welcome to {COMPANY_NAME} — Your account is ready"

    html_body = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; max-width: 560px;">
        <h2 style="color: #2557a7;">Hello {display_name},</h2>

        <p>Your company account has been set up and is ready to use.</p>

        <p>
          <strong>To get started:</strong> open the link below and sign in
          with this email address. You will receive a one-time code each
          time you log in — no password to remember.
        </p>

        <p style="margin: 20px 0;">
          <a href="{PORTAL_URL}"
             style="background:#2557a7; color:white; padding:10px 18px;
                    border-radius:6px; text-decoration:none; font-weight:bold;">
            Open the portal →
          </a>
        </p>

        <p>
          <strong>Attached</strong> is a PDF with your account details.
          It is password-protected — use your email address to open it.
        </p>

        <p style="color:#777; font-size:13px;">
          If you have any trouble getting started, reply to this email or contact IT directly.
        </p>

        <hr style="border:none; border-top:1px solid #eee; margin:24px 0;">
        <p style="color:#aaa; font-size:11px;">
          This message was sent by the {COMPANY_NAME} IT portal.
          Do not share your credentials with anyone.
        </p>
      </body>
    </html>
    """

    text_body = (
        f"Hello {display_name},\n\n"
        f"Your company account has been set up.\n\n"
        f"To get started, open the portal at:\n{PORTAL_URL}\n\n"
        f"Sign in with this email address ({recipient_email}). "
        f"You will receive a one-time code — no password needed.\n\n"
        f"Attached is a PDF with your account details. "
        f"It is password-protected using your email address.\n\n"
        f"If you need help, contact IT.\n\n"
        f"— {COMPANY_NAME} IT"
    )

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = f"{COMPANY_NAME} IT <{SENDER_EMAIL}>"
    msg["To"] = recipient_email

    # Plain text + HTML alternatives
    alternatives = MIMEMultipart("alternative")
    alternatives.attach(MIMEText(text_body, "plain", "utf-8"))
    alternatives.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alternatives)

    # Clean non-alphanumeric characters for safe filename
    safe_company_name = re.sub(r"[^\w\-_]", "", COMPANY_NAME.replace(" ", "_"))
    filename = f"{safe_company_name}_Account_Credentials.pdf"

    # Encrypted PDF attachment
    attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
    attachment.add_header(
        "Content-Disposition",
        "attachment",
        filename=filename,
    )
    msg.attach(attachment)

    # Dynamic connection handling (Port 587 STARTTLS vs Port 465 SSL/TLS)
    if SMTP_PORT == 587:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SENDER_EMAIL, recipient_email, msg.as_string())
    else:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SENDER_EMAIL, recipient_email, msg.as_string())

    print(f"[mailer] Welcome email with encrypted PDF sent to {recipient_email}")