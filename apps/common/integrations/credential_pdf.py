"""
credential_pdf.py - AES-256 encrypted PDF with an employee's login details.

Contains the login (email) and the temporary password shared by the sign-in and the NAS.
The PDF is generated in memory and never written to disk.
"""

import io
from datetime import date

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _build_unencrypted_pdf(company_name, employee_name, email, password, portal_url) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2.5 * cm, rightMargin=2.5 * cm,
                            topMargin=2.5 * cm, bottomMargin=2.5 * cm)
    styles = getSampleStyleSheet()
    brand = colors.HexColor("#2557a7")
    light = colors.HexColor("#f5f5f5")
    dark = colors.HexColor("#333333")
    muted = colors.HexColor("#777777")

    title = ParagraphStyle("Title", parent=styles["Title"], fontSize=20, textColor=brand,
                           spaceAfter=4, fontName="Helvetica-Bold")
    subtitle = ParagraphStyle("Subtitle", parent=styles["Normal"], fontSize=11, textColor=muted,
                              fontName="Helvetica")
    body = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10, textColor=dark,
                          spaceAfter=6, leading=15, fontName="Helvetica")
    note = ParagraphStyle("Note", parent=styles["Normal"], fontSize=9, textColor=muted,
                          leading=13, fontName="Helvetica-Oblique")

    content = [
        Paragraph(company_name, title),
        Paragraph("IT Access Credentials", subtitle),
        Spacer(1, 0.4 * cm),
        HRFlowable(width="100%", thickness=1.5, color=brand),
        Spacer(1, 0.5 * cm),
        Paragraph(f"Hello <b>{employee_name or email}</b>,", body),
        Paragraph("Your company accounts have been set up. The same temporary password is used for "
                  "the portal sign-in and for the company file server (NAS).", body),
        Spacer(1, 0.4 * cm),
    ]

    table = Table(
        [
            ["Portal", portal_url],
            ["Login (email)", email],
            ["NAS username", email],
            ["Temporary password", password],
            ["Issued on", date.today().strftime("%d %B %Y")],
        ],
        colWidths=[4.5 * cm, None],
        hAlign="LEFT",
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), light),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e8eef8")),
        ("TEXTCOLOR", (0, 0), (0, -1), brand),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    content += [table, Spacer(1, 0.6 * cm)]

    content += [
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#dddddd")),
        Spacer(1, 0.3 * cm),
        Paragraph("<b>Getting started</b>", body),
        Paragraph("1. Open the portal and sign in with your email address and the temporary password.", body),
        Paragraph("2. Use the same password to open the company file server (NAS).", body),
        Paragraph("3. Change your password from your profile page as soon as possible. If you change it "
                  "there, the new password applies to both systems.", body),
        Spacer(1, 0.6 * cm),
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#dddddd")),
        Spacer(1, 0.3 * cm),
        Paragraph("This document is password-protected. Keep it confidential. If you suspect your "
                  "credentials have been compromised, contact IT immediately.", note),
    ]
    doc.build(content)
    return buf.getvalue()


def generate_encrypted_pdf(company_name, employee_name, email, password, portal_url, passphrase=None) -> bytes:
    """Returns the encrypted PDF as bytes.

    `passphrase` opens the PDF. It defaults to the recipient's email address. Pass a value
    shared by phone or in person for stronger protection.
    """
    raw = _build_unencrypted_pdf(company_name, employee_name, email, password, portal_url)
    reader = PdfReader(io.BytesIO(raw))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    secret = passphrase or email
    writer.encrypt(user_password=secret, owner_password=secret, algorithm="AES-256")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()