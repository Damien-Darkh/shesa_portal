from credential_pdf import generate_encrypted_pdf

# Generate sample bytes using test data
pdf_bytes = generate_encrypted_pdf(
    company_name="Shesa Architects",
    employee_name="Jane Doe",
    email="jane@shesa.it",
    dsm_username="jane",
    portal_url="https://vpn.shesa.it",
    passphrase="Password123",  # Passphrase to open the file
)

# Write to a file you can open and inspect
with open("sample_credentials.pdf", "wb") as f:
    f.write(pdf_bytes)

print("Sample PDF generated: sample_credentials.pdf (Password: Password123)")