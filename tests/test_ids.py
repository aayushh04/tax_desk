"""Tests for PAN / GSTIN / ISIN helpers."""

import random

from taxdesk.ids import (gstin_check_char, isin_check_digit, is_valid_pan, make_gstin, make_pan,
                         mask_pan, validate_gstin)


def test_known_public_example_gstins_pass_checksum() -> None:
    """Two example GSTINs widely used in GST tutorials have correct check characters."""
    for gstin in ("27AAPFU0939F1ZV", "29AAGCB7383J1Z4"):
        assert gstin_check_char(gstin[:14]) == gstin[14]
        assert validate_gstin(gstin).valid


def test_one_wrong_character_is_caught() -> None:
    result = validate_gstin("27AAPFU0939F1ZX")
    assert not result.valid and "check character" in result.reason


def test_bad_gstins_are_flagged_not_crashing() -> None:
    for bad in (None, "", "   ", "27AAPFU0939F1Z", "27aapfu0939f1zv1", "00AAPFU0939F1ZV", 12345):
        assert validate_gstin(bad).valid is False
    assert validate_gstin(" 27aapfu0939f1zv ").valid  # case and spaces are tolerated


def test_generated_gstin_is_valid() -> None:
    rng = random.Random(1)
    pan = make_pan(rng, "C", "S")
    assert is_valid_pan(pan)
    assert validate_gstin(make_gstin(27, pan)).valid


def test_mask_pan() -> None:
    assert mask_pan("ABCDE1234F") == "ABCDE****F"
    assert mask_pan("abcde1234f") == "ABCDE****F"
    assert mask_pan("SHORT") == "*****"


def test_isin_check_digit_on_public_example() -> None:
    assert isin_check_digit("US037833100") == "5"   # US0378331005 is a well-known example ISIN
