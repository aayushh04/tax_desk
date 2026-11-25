"""PAN, GSTIN and ISIN helpers: format checks, check characters, masking, fake generation.

PAN (10 chars):   AAAAA9999A
    chars 1-3  any letters
    char 4     holder type: P person, C company, F firm/LLP, H HUF, T trust, ...
    char 5     first letter of the surname (person) or of the name (others)
    chars 6-9  digits, char 10 a letter

GSTIN (15 chars): 27 AAPFU0939F 1 Z V
    2 digits state code | 10-char PAN | entity number (1-9, A-Z) | 'Z' | check character
    The check character is a base-36 "Luhn mod 36" checksum of the first 14 chars,
    so a single mistyped character is almost always caught.

ISIN (12 chars):  IN F 123A01AB1 2 -> country, issuer/security code, Luhn check digit.
"""

from __future__ import annotations

import random
import re
import string
from dataclasses import dataclass

from taxdesk.rules import valid_gst_state_codes

BASE36 = string.digits + string.ascii_uppercase  # '0'..'9' then 'A'..'Z' -> values 0..35

PAN_RE = re.compile(r"^[A-Z]{3}[PCHFATBLJG][A-Z][0-9]{4}[A-Z]$")
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{3}[PCHFATBLJG][A-Z][0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


# ---------------------------------------------------------------- PAN ----------

def is_valid_pan(pan: str) -> bool:
    """True if the text has the PAN shape (AAAAA9999A with a valid holder-type letter)."""
    return bool(PAN_RE.match(str(pan).strip().upper()))


def mask_pan(pan: str) -> str:
    """Hide the 4 digits of a PAN for display: 'ABCDE1234F' -> 'ABCDE****F'.

    Anything that is not 10 characters is masked completely, so a wrong value is never shown.
    """
    pan = str(pan).strip().upper()
    if len(pan) != 10:
        return "*" * len(pan)
    return pan[:5] + "****" + pan[9]


def make_pan(rng: random.Random, holder_type: str, name_initial: str) -> str:
    """Create a fake PAN with a correct shape. Not a real PAN: the letters/digits are random."""
    letters = "".join(rng.choice(string.ascii_uppercase) for _ in range(3))
    digits = f"{rng.randint(0, 9999):04d}"
    return f"{letters}{holder_type}{name_initial.upper()}{digits}{rng.choice(string.ascii_uppercase)}"


# ---------------------------------------------------------------- GSTIN --------

def gstin_check_char(first14: str) -> str:
    """Compute the 15th (check) character of a GSTIN from its first 14 characters.

    For each character: take its base-36 value, multiply by 1 or 2 alternately,
    then add the "tens" and "units" of the product in base 36. The check value
    is whatever brings the total up to a multiple of 36.
    """
    total = 0
    for i, ch in enumerate(first14.upper()):
        product = BASE36.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return BASE36[(36 - total % 36) % 36]


@dataclass(frozen=True)
class GstinCheck:
    """Result of validating one GSTIN. `reason` is empty when valid."""

    gstin: str
    valid: bool
    reason: str = ""


def validate_gstin(gstin: object) -> GstinCheck:
    """Check a GSTIN's length, shape, state code and check character. Never raises."""
    text = "" if gstin is None else str(gstin).strip().upper()
    if not text or text in {"NAN", "NONE"}:
        return GstinCheck(text, False, "GSTIN is blank")
    if len(text) != 15:
        return GstinCheck(text, False, f"GSTIN must be 15 characters, got {len(text)}")
    if not GSTIN_RE.match(text):
        return GstinCheck(text, False, "GSTIN does not follow the 99AAAAA9999A9Z9 pattern")
    if text[:2] not in valid_gst_state_codes():
        return GstinCheck(text, False, f"unknown state code {text[:2]}")
    expected = gstin_check_char(text[:14])
    if text[14] != expected:
        return GstinCheck(text, False, f"check character should be {expected}, found {text[14]}")
    return GstinCheck(text, True)


def make_gstin(state_code: int, pan: str, entity_number: str = "1") -> str:
    """Build a GSTIN with a correct check character from a state code and PAN."""
    first14 = f"{state_code:02d}{pan}{entity_number}Z"
    return first14 + gstin_check_char(first14)


# ---------------------------------------------------------------- ISIN ---------

def isin_check_digit(first11: str) -> str:
    """Luhn check digit for an ISIN: letters become numbers (A=10 ... Z=35), then Luhn."""
    digits = "".join(str(BASE36.index(ch)) for ch in first11.upper())
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d) * (2 if i % 2 == 0 else 1)
        total += n // 10 + n % 10
    return str((10 - total % 10) % 10)


def make_fake_isin(rng: random.Random) -> str:
    """Create a mutual-fund-style ISIN (INF...) with a valid check digit. Not a real security."""
    body = "INF" + "".join(rng.choice(BASE36) for _ in range(8))
    return body + isin_check_digit(body)
