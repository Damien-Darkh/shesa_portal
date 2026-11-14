"""Identity Document Numbering System: XXY-XXXXXX (e.g. SAJ-347916).

Letters 1-2 come from the first name, letter 3 from the last name (uppercase).
Six digits come from the mobile number. Uniqueness is checked against the database;
randomness alone is not relied on.
"""
import random
import re
import secrets

from django.db import IntegrityError

MAX_ATTEMPTS = 200
ID_RE = re.compile(r"^[A-Z]{3}-\d{6}$")


class IdentityIdError(Exception):
    pass


def _letters(name: str) -> list[str]:
    return [c for c in (name or "").upper() if c.isalpha() and c.isascii()]


def _digits(phone: str) -> list[str]:
    return [c for c in (phone or "") if c.isdigit()]


def _all_six_digit_selections(digits: list[str]) -> set[str]:
    """Every distinct ordered six-digit selection from the number (subsequences)."""
    out = set()
    n = len(digits)
    if n < 6:
        return out
    # Choose 6 positions in order from n digits.
    from itertools import combinations
    for idx in combinations(range(n), 6):
        out.add("".join(digits[i] for i in idx))
    return out


def _letter_candidates(first: str, last: str) -> list[str]:
    firsts = _letters(first)
    lasts = _letters(last)
    if len(firsts) < 2 or not lasts:
        raise IdentityIdError("First name needs at least two letters and last name at least one.")
    out = set()
    from itertools import permutations
    for pair in permutations(range(len(firsts)), 2):
        a, b = pair
        for c in lasts:
            out.add(firsts[a] + firsts[b] + c)
    return sorted(out)


def generate(first_name: str, last_name: str, mobile: str, exists) -> str:
    """Returns a unique identity ID. `exists(candidate) -> bool` checks the database.

    Raises IdentityIdError if the inputs cannot produce an ID or no unique one is found.
    """
    digits = _digits(mobile)
    if len(digits) < 6:
        raise IdentityIdError("A mobile number with at least six digits is needed to create an ID.")

    letter_opts = _letter_candidates(first_name, last_name)
    digit_opts = sorted(_all_six_digit_selections(digits))
    if not digit_opts:
        raise IdentityIdError("Mobile number does not yield six digits.")

    for _ in range(MAX_ATTEMPTS):
        candidate = f"{secrets.choice(letter_opts)}-{secrets.choice(digit_opts)}"
        if not exists(candidate):
            return candidate
    raise IdentityIdError("Could not find an unused ID. Try again or check the name and number.")