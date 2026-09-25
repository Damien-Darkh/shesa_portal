"""
Run once to create the database:

    python init_db.py

There's no admin account to set up here anymore - the very first person
who successfully logs in through WorkOS AuthKit automatically becomes
the portal's first admin (see the before_request/callback hooks in
app.py). Make sure YOU are the first person to visit the portal after
this step.
"""
from dotenv import load_dotenv
load_dotenv()

from app import app  # noqa: E402
from models import db  # noqa: E402

with app.app_context():
    db.create_all()

print("Database ready. The first person to log in through WorkOS AuthKit "
      "will automatically become the admin - visit the portal yourself "
      "first.")
