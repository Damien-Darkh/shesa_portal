"""One place that generates temporary passwords. Used for both Authentik and the NAS."""
import secrets
import string

SPECIALS = "!@#$%^*()_+-="


def generate(avoid: str = "", length: int = 20) -> str:
    """Random password that satisfies the NAS and Authentik complexity rules.

    `avoid` is a string the password must not contain (the account email).
    """
    alphabet = string.ascii_letters + string.digits + SPECIALS
    avoid = (avoid or "").lower()
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.islower() for c in pwd)
            and any(c.isupper() for c in pwd)
            and any(c.isdigit() for c in pwd)
            and any(c in SPECIALS for c in pwd)
            and (not avoid or avoid not in pwd.lower())
        ):
            return pwd