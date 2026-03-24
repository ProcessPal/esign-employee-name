"""Tests for src/esign/extractor.py."""

from pathlib import Path

import pytest

from esign.extractor import ExtractionResult, TextLocation, find_text_locations

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


def test_find_employee_name():
    """sample.pdf contains 'Employee Name' — expect at least one result."""
    extraction = find_text_locations(_load("sample.pdf"))
    assert isinstance(extraction, ExtractionResult)
    assert len(extraction.locations) >= 1
    assert extraction.pages_scanned >= 1
    loc = extraction.locations[0]
    assert isinstance(loc, TextLocation)
    assert loc.page_index == 0
    x0, y0, x1, y1 = loc.box
    assert x0 < x1
    assert y0 < y1


def test_no_match_returns_empty():
    """no-match.pdf has no 'Employee Name' — expect empty list."""
    extraction = find_text_locations(_load("no-match.pdf"))
    assert extraction.locations == []
    assert extraction.pages_scanned >= 1


def test_multi_match():
    """multi-match.pdf has 'Employee Name' twice — expect exactly 2 results."""
    extraction = find_text_locations(_load("multi-match.pdf"))
    assert len(extraction.locations) == 2


def test_case_insensitive():
    """Search must be case-insensitive; sample.pdf has 'Employee Name' (mixed case)."""
    results_default = find_text_locations(_load("sample.pdf"))
    results_lower = find_text_locations(_load("sample.pdf"), search_text="employee name")
    assert len(results_default.locations) >= 1
    assert len(results_lower.locations) >= 1


def test_coordinates_within_page():
    """All returned bounding boxes must fall within page dimensions."""
    for fixture in ("sample.pdf", "multi-match.pdf"):
        extraction = find_text_locations(_load(fixture))
        for loc in extraction.locations:
            x0, y0, x1, y1 = loc.box
            assert 0 <= x0 < x1 <= loc.page_width, f"{fixture}: x coords out of range"
            assert 0 <= y0 < y1 <= loc.page_height, f"{fixture}: y coords out of range"


# ---------------------------------------------------------------------------
# Error-handling tests
# ---------------------------------------------------------------------------


def test_invalid_pdf_raises():
    """Non-PDF bytes must raise ValueError."""
    with pytest.raises(ValueError, match="Invalid PDF"):
        find_text_locations(b"this is not a pdf")


def test_empty_bytes_raises():
    """Empty bytes must raise ValueError."""
    with pytest.raises(ValueError, match="Invalid PDF"):
        find_text_locations(b"")
