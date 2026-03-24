"""Tests for src/esign/signer.py — signature field placement."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from pyhanko.pdf_utils.reader import PdfFileReader

from esign.signer import PrepareResult, SignatureFieldResult, add_signature_fields

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Letter-size page: 612 x 792 points
LETTER_WIDTH = 612.0
LETTER_HEIGHT = 792.0

# A single location near the middle of a letter-size page
SINGLE_LOCATION = [(0, (50.0, 600.0, 150.0, 612.0), LETTER_WIDTH, LETTER_HEIGHT)]

# Two locations on page 0 for multi-match tests
TWO_LOCATIONS = [
    (0, (50.0, 600.0, 150.0, 612.0), LETTER_WIDTH, LETTER_HEIGHT),
    (0, (50.0, 500.0, 150.0, 512.0), LETTER_WIDTH, LETTER_HEIGHT),
]


def _read_field_names(pdf_bytes: bytes) -> set[str]:
    """Return all AcroForm field names present in pdf_bytes."""
    reader = PdfFileReader(BytesIO(pdf_bytes))
    acroform = reader.root.get("/AcroForm")
    if not acroform:
        return set()
    acroform_obj = acroform.get_object() if hasattr(acroform, "get_object") else acroform
    fields_ref = acroform_obj.get("/Fields", [])
    fields_list = fields_ref.get_object() if hasattr(fields_ref, "get_object") else fields_ref
    names: set[str] = set()
    for item in fields_list:
        fobj = item.get_object() if hasattr(item, "get_object") else item
        t = fobj.get("/T")
        if t is not None:
            names.add(str(t))
    return names


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_bytes() -> bytes:
    return (FIXTURES_DIR / "sample.pdf").read_bytes()


@pytest.fixture
def multi_match_bytes() -> bytes:
    return (FIXTURES_DIR / "multi-match.pdf").read_bytes()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_add_single_field(sample_bytes: bytes) -> None:
    result = add_signature_fields(sample_bytes, SINGLE_LOCATION)

    assert isinstance(result, PrepareResult)
    assert len(result.pdf_bytes) > len(sample_bytes), "Output should be larger than input"
    assert result.pdf_bytes[:4] == b"%PDF", "Output must be a valid PDF"
    assert len(result.fields_added) == 1
    assert len(result.fields_skipped) == 0


def test_add_multiple_fields(multi_match_bytes: bytes) -> None:
    result = add_signature_fields(multi_match_bytes, TWO_LOCATIONS)

    assert len(result.fields_added) == 2
    assert len(result.fields_skipped) == 0
    names = _read_field_names(result.pdf_bytes)
    assert "EmployeeSig_p0_0" in names
    assert "EmployeeSig_p0_1" in names


def test_empty_locations_returns_unchanged(sample_bytes: bytes) -> None:
    result = add_signature_fields(sample_bytes, [])

    assert result.pdf_bytes == sample_bytes
    assert result.fields_added == []
    assert result.fields_skipped == []


def test_box_clamping(sample_bytes: bytes) -> None:
    # Place a box partially outside the right/top edge
    near_edge_location = [(0, (580.0, 770.0, 620.0, 800.0), LETTER_WIDTH, LETTER_HEIGHT)]
    result = add_signature_fields(
        sample_bytes,
        near_edge_location,
        padding=10.0,
        min_width=0.0,
        min_height=0.0,
    )

    assert len(result.fields_added) == 1
    box = result.fields_added[0].box
    x0, y0, x1, y1 = box
    assert x0 >= 0.0
    assert y0 >= 0.0
    assert x1 <= LETTER_WIDTH
    assert y1 <= LETTER_HEIGHT


def test_minimum_field_size(sample_bytes: bytes) -> None:
    # Tiny bounding box: 5x5 points
    tiny_location = [(0, (100.0, 400.0, 105.0, 405.0), LETTER_WIDTH, LETTER_HEIGHT)]
    result = add_signature_fields(
        sample_bytes,
        tiny_location,
        padding=0.0,
        min_width=200.0,
        min_height=50.0,
    )

    assert len(result.fields_added) == 1
    box = result.fields_added[0].box
    x0, y0, x1, y1 = box
    assert (x1 - x0) >= 200.0, "Width should meet min_width"
    assert (y1 - y0) >= 50.0, "Height should meet min_height"


def test_field_naming(sample_bytes: bytes) -> None:
    result = add_signature_fields(sample_bytes, SINGLE_LOCATION, field_name_prefix="MySig")

    assert len(result.fields_added) == 1
    assert result.fields_added[0].field_name == "MySig_p0_0"
    names = _read_field_names(result.pdf_bytes)
    assert "MySig_p0_0" in names


def test_invalid_pdf_raises() -> None:
    with pytest.raises(ValueError, match="Cannot process PDF"):
        add_signature_fields(b"this is not a PDF", SINGLE_LOCATION)


def test_reprocess_skips_duplicates(sample_bytes: bytes) -> None:
    # First pass: adds the field
    first = add_signature_fields(sample_bytes, SINGLE_LOCATION)
    assert len(first.fields_added) == 1
    assert len(first.fields_skipped) == 0

    # Second pass: same location → field already exists, must be skipped
    second = add_signature_fields(first.pdf_bytes, SINGLE_LOCATION)
    assert len(second.fields_added) == 0
    assert len(second.fields_skipped) == 1
    assert second.fields_skipped[0] == "EmployeeSig_p0_0"
