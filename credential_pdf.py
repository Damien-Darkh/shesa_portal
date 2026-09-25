"""
credential_pdf.py - Generates an AES-256 encrypted PDF containing an
employee's initial NAS credentials.

The PDF is encrypted with a passphrase that is NEVER sent over email -
it must be communicated separately (phone call, Signal message, in person).
This means an attacker who intercepts only the email gets an encrypted
file they cannot open.

Design choices:
- AES-256 (pypdf's "AES-256" algorithm) - strongest PDF encryption available.
  RC4-128 (pypdf's default) is broken and should never be used for sensitive data.
- The PDF itself is generated in memory (BytesIO) and passed directly to
  the mailer - it is never written to disk on the portal server.
- The passphrase should be derived from something the admin knows and the
  employee can verify, e.g. their date of birth in DDMMYYYY format, their
  employee ID, or a short random phrase the admin reads over the phone.
  NOT the employee's own email address (attacker already has that) and NOT
  a fixed company-wide passphrase.

Suggested passphrase strategy (tell admins this in the README):
  Use the employee's date of birth in DDMMYYYY format, or a short phrase
  you tell them verbally when you call to say their account is ready.
  Example admin script: "Your account is ready. The PDF attachment is
  protected - the password is your date of birth, numbers only, day-month-year."
"""

import io
from datetime import date

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from pypdf import PdfWriter, PdfReader


def _build_unencrypted_pdf(
    company_name: str,
    employee_name: str,
    email: str,
    dsm_username: str,
    dsm_passphrase: str,
    portal_url: str,
) -> bytes:
    """Builds the unencrypted PDF content in memory and returns the raw bytes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2.5 * cm,
        rightMargin=2.5 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2.5 * cm,
    )

    styles = getSampleStyleSheet()
    brand_blue = colors.HexColor("#2557a7")
    light_gray = colors.HexColor("#f5f5f5")
    dark_gray = colors.HexColor("#333333")
    muted = colors.HexColor("#777777")

    title_style = ParagraphStyle(
        "Title",
        parent=styles["Title"],
        fontSize=20,
        textColor=brand_blue,
        spaceAfter=4,
        fontName="Helvetica-Bold",
    )
    subtitle_style = ParagraphStyle(
        "Subtitle",
        parent=styles["Normal"],
        fontSize=11,
        textColor=muted,
        spaceAfter=0,
        fontName="Helvetica",
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontSize=10,
        textColor=dark_gray,
        spaceAfter=6,
        leading=15,
        fontName="Helvetica",
    )
    note_style = ParagraphStyle(
        "Note",
        parent=styles["Normal"],
        fontSize=9,
        textColor=muted,
        spaceAfter=4,
        leading=13,
        fontName="Helvetica-Oblique",
    )

    today = date.today().strftime("%d %B %Y")

    content = []

    # Header
    content.append(Paragraph(company_name, title_style))
    content.append(Paragraph("IT Access Credentials", subtitle_style))
    content.append(Spacer(1, 0.4 * cm))
    content.append(HRFlowable(width="100%", thickness=1.5, color=brand_blue))
    content.append(Spacer(1, 0.5 * cm))

    content.append(Paragraph(
        f"Hello <b>{employee_name or email}</b>,",
        body_style,
    ))
    content.append(Paragraph(
        "Your company accounts have been set up. This document contains your "
        "initial login credentials. Please follow the steps below to get started.",
        body_style,
    ))
    content.append(Spacer(1, 0.4 * cm))

    # Credentials box
    cred_data = [
        ["Portal URL", portal_url],
        ["Your email (login)", email],
        ["NAS username", dsm_username],
        ["NAS password", dsm_passphrase],
        ["Issued on", today],
    ]
    cred_table = Table(
        cred_data,
        colWidths=[4.5 * cm, None],
        hAlign="LEFT",
    )
    cred_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), light_gray),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e8eef8")),
        ("TEXTCOLOR", (0, 0), (0, -1), brand_blue),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ROWBACKGROUND", (0, 0), (-1, -1), [light_gray, colors.white]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
    ]))
    content.append(cred_table)
    content.append(Spacer(1, 0.6 * cm))

    # NAS password notice - intentionally not included in the PDF
    content.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#dddddd")))
    content.append(Spacer(1, 0.3 * cm))
    content.append(Paragraph("<b>Your NAS password</b>", body_style))
    content.append(Paragraph(
        "Your temporary NAS password was communicated to you separately "
        "(by phone or in person) and is intentionally NOT included in this document. "
        "You will be asked to set your own password the first time you log in.",
        body_style,
    ))
    content.append(Spacer(1, 0.4 * cm))

    # Getting started steps
    content.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#dddddd")))
    content.append(Spacer(1, 0.3 * cm))
    content.append(Paragraph("<b>Getting started</b>", body_style))

    steps = [
        ("1.", f"Open the portal: <b>{portal_url}</b>"),
        ("2.", "Log in with your company email — you will receive a one-time code "
               "each time you sign in (no password to remember)."),
        ("3.", "Add your devices (laptop, phone) to get VPN access to the company network."),
        ("4.", "Use your NAS username and the temporary password you were told to access "
               "company files. You will be asked to set a new password immediately."),
    ]
    step_data = [[num, Paragraph(text, body_style)] for num, text in steps]
    step_table = Table(step_data, colWidths=[0.7 * cm, None], hAlign="LEFT")
    step_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), brand_blue),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    content.append(step_table)
    content.append(Spacer(1, 0.6 * cm))

    # Security notice
    content.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#dddddd")))
    content.append(Spacer(1, 0.3 * cm))
    content.append(Paragraph(
        "🔒  <b>Security notice</b> — This document is password-protected. "
        "Keep it confidential. If you suspect your credentials have been compromised, "
        f"contact IT immediately at {portal_url}.",
        note_style,
    ))

    doc.build(content)
    return buf.getvalue()


def generate_encrypted_pdf(
    company_name: str,
    employee_name: str,
    email: str,
    dsm_username: str,
    dsm_passphrase: str,
    portal_url: str,
) -> bytes:
    """
    Generates an AES-256 encrypted PDF containing the employee's initial
    credentials. The passphrase must be communicated to the employee via
    a separate channel (phone, Signal, in person) - never over email.

    Returns the encrypted PDF as bytes, ready to attach to an email.

    Args:
        company_name:  Displayed in the document header, e.g. "SHESA S.r.l."
        employee_name: Employee's display name for the greeting, e.g. "Maria Rossi"
        email:         Employee's email address (also their portal login)
        dsm_username:  Their Synology NAS username
        portal_url:    The portal's public URL, e.g. "https://vpn.shesa.it"
        passphrase:    The password to open this PDF - share out-of-band only
    """
    raw_pdf = _build_unencrypted_pdf(
        company_name=company_name,
        employee_name=employee_name,
        email=email,
        dsm_username=dsm_username,
        portal_url=portal_url,
        dsm_passphrase=dsm_passphrase
    )

    reader = PdfReader(io.BytesIO(raw_pdf))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    # AES-256 is the strongest algorithm pypdf supports.
    # RC4 (pypdf's default) is cryptographically broken - always specify explicitly.
    writer.encrypt(
        user_password=email,
        owner_password=email,
        algorithm="AES-256",
    )

    encrypted_buf = io.BytesIO()
    writer.write(encrypted_buf)
    return encrypted_buf.getvalue()