"""
mailer.py - Sends the welcome email with an encrypted PDF attachment.

The email body contains no credentials. The PDF contains the login (the employee's
email) and the temporary password shared by the sign-in and the NAS.
"""

import logging
import os
import re
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from apps.common.integrations import credential_pdf

SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtps.aruba.it")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 465))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "") or SMTP_USER
PORTAL_URL = os.environ.get("PUBLIC_APP_URL", "https://vpn.shesa.it").rstrip("/")
COMPANY_NAME = os.environ.get("COMPANY_NAME", "SHESA S.r.l.")

logger = logging.getLogger(__name__)


class MailError(Exception):
    pass


def send_welcome_email(
    recipient_email: str,
    password: str,
    first_name: str | None = None,
    last_name: str | None = None,
) -> None:
    """Sends the welcome email. Raises MailError if SMTP is not configured or delivery fails."""
    if not SMTP_SERVER or not SMTP_USER or not SMTP_PASSWORD or not SENDER_EMAIL:
        raise MailError("SMTP is not configured (SMTP_SERVER, SMTP_USER, SMTP_PASSWORD, SENDER_EMAIL).")
    if not password:
        raise MailError("No temporary password was provided to send.")

    display_name = first_name or recipient_email
    full_name = " ".join(filter(None, [first_name, last_name])) or recipient_email

    pdf_bytes = credential_pdf.generate_encrypted_pdf(
        company_name=COMPANY_NAME,
        employee_name=full_name,
        email=recipient_email,
        password=password,
        portal_url=PORTAL_URL,
    )

    subject = f"Welcome to {COMPANY_NAME}: your account is ready"
    text_body = (
        f"Hello {display_name},\n\n"
        f"Your company account has been set up.\n\n"
        f"Your login is your email address: {recipient_email}\n"
        f"Your temporary password is in the attached PDF. The same password works for the "
        f"portal and for the company file server.\n\n"
        f"Portal: {PORTAL_URL}\n\n"
        f"The PDF is password-protected with your email address.\n"
        f"If you need help, contact IT.\n\n"
        f"- {COMPANY_NAME} IT"
    )
    html_body = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; max-width: 560px;">
        <h2 style="color: #2557a7;">Hello {display_name},</h2>
        <p>Your company account has been set up.</p>
        <p><strong>Your login is your email address:</strong> {recipient_email}</p>
        <p>Your temporary password is in the attached PDF. The same password works for the
           portal and for the company file server.</p>
        <p style="margin: 20px 0;">
          <a href="{PORTAL_URL}" style="background:#2557a7; color:white; padding:10px 18px;
             border-radius:6px; text-decoration:none; font-weight:bold;">Open the portal</a>
        </p>
        <p style="color:#777; font-size:13px;">The PDF is password-protected with your email address.
           If you need help, contact IT.</p>
        <hr style="border:none; border-top:1px solid #eee; margin:24px 0;">
        <p style="color:#aaa; font-size:11px;">Sent by the {COMPANY_NAME} IT portal. Do not share your credentials.</p>
      </body>
    </html>
    """

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = f"{COMPANY_NAME} IT <{SENDER_EMAIL}>"
    msg["To"] = recipient_email

    alternatives = MIMEMultipart("alternative")
    alternatives.attach(MIMEText(text_body, "plain", "utf-8"))
    alternatives.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alternatives)

    safe_company = re.sub(r"[^\w\-_]", "", COMPANY_NAME.replace(" ", "_"))
    attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
    attachment.add_header("Content-Disposition", "attachment", filename=f"{safe_company}_Account_Credentials.pdf")
    msg.attach(attachment)

    try:
        if SMTP_PORT == 587:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=20) as server:
                server.ehlo()
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SENDER_EMAIL, recipient_email, msg.as_string())
        else:
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=20) as server:
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SENDER_EMAIL, recipient_email, msg.as_string())
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError("SMTP login was rejected. Check SMTP_USER and SMTP_PASSWORD.") from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise MailError(f"The mail server refused the recipient address {recipient_email}.") from exc
    except smtplib.SMTPSenderRefused as exc:
        raise MailError("The mail server rejected the sender. Check SENDER_EMAIL matches SMTP_USER.") from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(f"Could not reach the mail server: {exc.__class__.__name__}") from exc

    logger.info("Welcome email sent to %s", recipient_email)