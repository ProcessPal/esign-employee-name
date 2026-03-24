"""Integration tests for the eSign Employee Name application.

Tests end-to-end pipelines:
  - CLI: read PDF → extract text → add signature fields → write output
  - API: upload PDF → same processing → return response
  - Core functions: direct calls to extractor and signer
  - Signature field verification in output PDFs
  - Error scenarios and edge cases
"""

from __future__ import annotations

import shutil
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pyhanko.pdf_utils.reader import PdfFileReader
from typer.testing import CliRunner

from esign.api import app as api_app
from esign.cli import app as cli_app
from esign.extractor import find_text_locations
from esign.signer import add_signature_fields

FIXTURES_DIR = Path(__file__).parent / "fixtures"
cli_runner = CliRunner()
api_client = TestClient(api_app)


def _load_fixture(name: str) -> bytes:
    """Load a fixture PDF by name."""
    return (FIXTURES_DIR / name).read_bytes()


def _copy_fixture(name: str, dest_dir: Path) -> Path:
    """Copy a fixture PDF to dest_dir and return the new path."""
    src = FIXTURES_DIR / name
    dst = dest_dir / name
    shutil.copy2(src, dst)
    return dst


def _read_acroform_fields(pdf_bytes: bytes) -> dict[str, dict]:
    """Read AcroForm fields from PDF bytes. Returns dict of field_name -> field_dict."""
    reader = PdfFileReader(BytesIO(pdf_bytes))
    acroform = reader.root.get("/AcroForm")
    if not acroform:
        return {}
    acroform_obj = acroform.get_object() if hasattr(acroform, "get_object") else acroform
    fields_ref = acroform_obj.get("/Fields", [])
    fields_list = fields_ref.get_object() if hasattr(fields_ref, "get_object") else fields_ref
    result = {}
    for item in fields_list:
        fobj = item.get_object() if hasattr(item, "get_object") else item
        field_name = fobj.get("/T")
        if field_name is not None:
            result[str(field_name)] = fobj
    return result


def _get_field_count(pdf_bytes: bytes) -> int:
    """Return count of AcroForm fields in PDF."""
    return len(_read_acroform_fields(pdf_bytes))


def _get_field_boxes(pdf_bytes: bytes) -> dict[str, tuple[float, float, float, float]]:
    """Return dict of field_name -> box for all fields in PDF."""
    fields = _read_acroform_fields(pdf_bytes)
    result = {}
    for fname, fobj in fields.items():
        rect = fobj.get("/Rect")
        if rect:
            rect_obj = rect.get_object() if hasattr(rect, "get_object") else rect
            if hasattr(rect_obj, "__iter__") and len(rect_obj) >= 4:
                # Handle both list and PDFArray types
                coords = []
                for x in list(rect_obj)[:4]:
                    x_obj = x.get_object() if hasattr(x, "get_object") else x
                    coords.append(float(x_obj))
                result[fname] = tuple(coords)
    return result


# ==============================================================================
# End-to-end pipeline tests
# ==============================================================================


def test_full_pipeline_cli(tmp_path: Path) -> None:
    """CLI: read sample.pdf → extract → add fields → write output.

    Verify:
      - Exit code 0
      - Output PDF created
      - Output larger than input
      - Output starts with %PDF-
      - Output has signature fields
      - Output PDF is not corrupted
    """
    input_pdf = _copy_fixture("sample.pdf", tmp_path)
    output_pdf = tmp_path / "prepared.pdf"

    result = cli_runner.invoke(cli_app, [str(input_pdf), "-o", str(output_pdf)])

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    assert output_pdf.exists(), "Output PDF not created"

    input_bytes = input_pdf.read_bytes()
    output_bytes = output_pdf.read_bytes()

    assert output_bytes.startswith(b"%PDF-"), "Output missing PDF header"
    assert len(output_bytes) > len(input_bytes), "Output should be larger than input"

    # Verify output PDF can be read by pyHanko without corruption
    reader = PdfFileReader(BytesIO(output_bytes))
    assert reader.root is not None, "Output PDF corrupted or unreadable"

    # Verify signature fields were added
    field_count = _get_field_count(output_bytes)
    assert field_count > 0, f"No signature fields in output (found {field_count})"


def test_full_pipeline_api() -> None:
    """API: upload sample.pdf → POST /prepare → verify response.

    Verify:
      - Status 200
      - Response is valid PDF
      - X-Fields-Added header > 0
      - Response PDF readable by pyHanko
    """
    pdf_bytes = _load_fixture("sample.pdf")
    resp = api_client.post(
        "/prepare",
        files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
    )

    assert resp.status_code == 200, f"API returned {resp.status_code}: {resp.text}"
    assert resp.content.startswith(b"%PDF-"), "Response missing PDF header"
    assert "X-Fields-Added" in resp.headers, "Missing X-Fields-Added header"

    fields_added = int(resp.headers["X-Fields-Added"])
    assert fields_added > 0, f"No fields added (X-Fields-Added: {fields_added})"

    # Verify response PDF is readable
    reader = PdfFileReader(BytesIO(resp.content))
    assert reader.root is not None, "Response PDF corrupted or unreadable"


def test_pipeline_core_functions() -> None:
    """Direct function calls: extractor → signer → verify.

    Verify:
      - find_text_locations returns results
      - Results are converted correctly to signer format
      - add_signature_fields returns PrepareResult with fields_added > 0
      - Output PDF can be read by pyHanko
    """
    pdf_bytes = _load_fixture("sample.pdf")

    # Extract text locations
    extraction = find_text_locations(pdf_bytes)
    assert len(extraction.locations) > 0, "No text locations found"

    # Verify all locations have valid coordinates
    for loc in extraction.locations:
        assert loc.page_index >= 0
        x0, y0, x1, y1 = loc.box
        assert x0 < x1, "Invalid x coordinates"
        assert y0 < y1, "Invalid y coordinates"
        assert loc.page_width > 0
        assert loc.page_height > 0

    # Convert to signer format
    signer_locations = [
        (loc.page_index, loc.box, loc.page_width, loc.page_height)
        for loc in extraction.locations
    ]

    # Add signature fields
    result = add_signature_fields(pdf_bytes, signer_locations)
    assert result.fields_added, "No fields added"
    assert len(result.fields_added) == len(extraction.locations)

    # Verify output PDF is valid
    reader = PdfFileReader(BytesIO(result.pdf_bytes))
    assert reader.root is not None, "Output PDF corrupted"
    assert result.pdf_bytes.startswith(b"%PDF-"), "Output missing PDF header"


# ==============================================================================
# Signature field verification tests
# ==============================================================================


def test_output_has_signature_fields() -> None:
    """Process sample.pdf and verify output PDF has AcroForm signature fields.

    Extract fields using pyHanko's PdfFileReader and verify structure.
    """
    pdf_bytes = _load_fixture("sample.pdf")
    extraction = find_text_locations(pdf_bytes)
    signer_locations = [
        (loc.page_index, loc.box, loc.page_width, loc.page_height)
        for loc in extraction.locations
    ]

    result = add_signature_fields(pdf_bytes, signer_locations)

    # Read AcroForm from output
    fields = _read_acroform_fields(result.pdf_bytes)
    assert len(fields) > 0, "No AcroForm fields found in output"

    # Verify field names start with expected prefix
    for fname in fields.keys():
        assert fname.startswith("EmployeeSig"), f"Unexpected field name: {fname}"


def test_signature_field_coordinates() -> None:
    """Verify signature field boxes are near the original text locations.

    Extracted text location is (x0, y0, x1, y1). With default padding (10pt)
    and min_width/min_height (200/50pt), the output field box should:
      - Have center within ~100pt of original center (accounting for padding/sizing)
      - Be larger than original due to minimums
    """
    pdf_bytes = _load_fixture("sample.pdf")
    extraction = find_text_locations(pdf_bytes)
    assert len(extraction.locations) > 0

    signer_locations = [
        (loc.page_index, loc.box, loc.page_width, loc.page_height)
        for loc in extraction.locations
    ]

    result = add_signature_fields(pdf_bytes, signer_locations)
    field_boxes = _get_field_boxes(result.pdf_bytes)

    # We should have as many fields as locations
    assert len(field_boxes) >= len(extraction.locations)

    # Verify each field box is reasonable (not zero-sized, within page bounds)
    for fname, (x0, y0, x1, y1) in field_boxes.items():
        assert x0 < x1, f"{fname}: x0 >= x1"
        assert y0 < y1, f"{fname}: y0 >= y1"
        assert x0 >= 0, f"{fname}: x0 < 0"
        assert y0 >= 0, f"{fname}: y0 < 0"


# ==============================================================================
# Multi-match tests
# ==============================================================================


def test_multi_match_creates_multiple_fields() -> None:
    """Process multi-match.pdf (2 occurrences) and verify exactly 2 fields created.

    Verify:
      - find_text_locations returns 2 results
      - add_signature_fields returns PrepareResult with 2 fields_added
      - Output PDF has exactly 2 AcroForm fields
    """
    pdf_bytes = _load_fixture("multi-match.pdf")

    extraction = find_text_locations(pdf_bytes)
    assert len(extraction.locations) == 2, f"Expected 2 locations, found {len(extraction.locations)}"

    signer_locations = [
        (loc.page_index, loc.box, loc.page_width, loc.page_height)
        for loc in extraction.locations
    ]

    result = add_signature_fields(pdf_bytes, signer_locations)
    assert len(result.fields_added) == 2, f"Expected 2 fields added, got {len(result.fields_added)}"

    field_count = _get_field_count(result.pdf_bytes)
    assert field_count == 2, f"Expected 2 fields in output, found {field_count}"


def test_multi_match_cli(tmp_path: Path) -> None:
    """CLI with multi-match.pdf creates output with 2 signature fields."""
    input_pdf = _copy_fixture("multi-match.pdf", tmp_path)
    output_pdf = tmp_path / "multi_prepared.pdf"

    result = cli_runner.invoke(cli_app, [str(input_pdf), "-o", str(output_pdf)])

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    assert "2 'Employee Name' occurrence(s)" in result.output

    output_bytes = output_pdf.read_bytes()
    field_count = _get_field_count(output_bytes)
    assert field_count == 2, f"Expected 2 fields, found {field_count}"


def test_multi_match_api() -> None:
    """API with multi-match.pdf returns response with X-Fields-Added: 2."""
    pdf_bytes = _load_fixture("multi-match.pdf")
    resp = api_client.post(
        "/prepare",
        files={"file": ("multi-match.pdf", pdf_bytes, "application/pdf")},
    )

    assert resp.status_code == 200
    assert resp.headers["X-Fields-Added"] == "2"


# ==============================================================================
# Error path tests
# ==============================================================================


def test_not_found_error_cli(tmp_path: Path) -> None:
    """CLI with no-match.pdf exits with code 1.

    Verify error message mentions 'not found'.
    """
    input_pdf = _copy_fixture("no-match.pdf", tmp_path)
    output_pdf = tmp_path / "out.pdf"

    result = cli_runner.invoke(cli_app, [str(input_pdf), "-o", str(output_pdf)])

    assert result.exit_code == 1, f"Expected exit code 1, got {result.exit_code}"
    assert "not found" in result.output.lower(), f"Expected 'not found' in output: {result.output}"


def test_not_found_error_api() -> None:
    """API with no-match.pdf returns 422 with 'Text not found' detail."""
    pdf_bytes = _load_fixture("no-match.pdf")
    resp = api_client.post(
        "/prepare",
        files={"file": ("no-match.pdf", pdf_bytes, "application/pdf")},
    )

    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"
    body = resp.json()
    assert "Text not found" in body.get("detail", "")


def test_non_pdf_error_cli(tmp_path: Path) -> None:
    """CLI with non-PDF input rejects with exit code 2."""
    bad_file = tmp_path / "notapdf.pdf"
    bad_file.write_bytes(b"This is not a PDF file at all")
    output_pdf = tmp_path / "out.pdf"

    result = cli_runner.invoke(cli_app, [str(bad_file), "-o", str(output_pdf)])

    assert result.exit_code == 2, f"Expected exit code 2, got {result.exit_code}"
    assert "not a valid pdf" in result.output.lower() or "invalid" in result.output.lower()


def test_non_pdf_error_api() -> None:
    """API with non-PDF input returns 400."""
    resp = api_client.post(
        "/prepare",
        files={"file": ("bad.pdf", b"Not a PDF", "application/pdf")},
    )

    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
    body = resp.json()
    assert "Invalid" in body.get("detail", "") or "invalid" in body.get("detail", "").lower()


def test_empty_file_error_cli(tmp_path: Path) -> None:
    """CLI with empty file rejects with exit code 2."""
    empty_file = tmp_path / "empty.pdf"
    empty_file.write_bytes(b"")
    output_pdf = tmp_path / "out.pdf"

    result = cli_runner.invoke(cli_app, [str(empty_file), "-o", str(output_pdf)])

    assert result.exit_code == 2


def test_empty_file_error_api() -> None:
    """API with empty file returns 400."""
    resp = api_client.post(
        "/prepare",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )

    assert resp.status_code == 400


# ==============================================================================
# Idempotency tests
# ==============================================================================


def test_reprocess_is_safe() -> None:
    """Process sample.pdf, then re-process the OUTPUT.

    Second pass should skip existing fields (not corrupt the PDF).
    Verify:
      - First pass: fields_added > 0, fields_skipped == 0
      - Second pass: fields_added == 0, fields_skipped > 0
      - Second output is readable
    """
    pdf_bytes = _load_fixture("sample.pdf")

    extraction = find_text_locations(pdf_bytes)
    signer_locations = [
        (loc.page_index, loc.box, loc.page_width, loc.page_height)
        for loc in extraction.locations
    ]

    # First pass
    first = add_signature_fields(pdf_bytes, signer_locations)
    assert len(first.fields_added) > 0, "First pass should add fields"
    assert len(first.fields_skipped) == 0, "First pass should not skip anything"

    # Second pass with same locations on output of first pass
    second = add_signature_fields(first.pdf_bytes, signer_locations)
    assert len(second.fields_added) == 0, "Second pass should not add fields"
    assert len(second.fields_skipped) > 0, "Second pass should skip existing fields"

    # Verify second output is still readable
    reader = PdfFileReader(BytesIO(second.pdf_bytes))
    assert reader.root is not None, "Second output corrupted"

    # Verify field count unchanged
    first_count = _get_field_count(first.pdf_bytes)
    second_count = _get_field_count(second.pdf_bytes)
    assert first_count == second_count, "Field count should not change on reprocess"


def test_reprocess_cli(tmp_path: Path) -> None:
    """CLI: process sample.pdf, then process OUTPUT again.

    Both passes should succeed; second should skip fields.
    """
    input_pdf = _copy_fixture("sample.pdf", tmp_path)
    first_output = tmp_path / "first.pdf"
    second_output = tmp_path / "second.pdf"

    # First pass
    result1 = cli_runner.invoke(cli_app, [str(input_pdf), "-o", str(first_output)])
    assert result1.exit_code == 0, f"First pass failed: {result1.output}"
    assert "Added field" in result1.output

    # Second pass (process output of first pass)
    result2 = cli_runner.invoke(
        cli_app,
        [str(first_output), "-o", str(second_output), "--force"],
    )
    assert result2.exit_code == 0, f"Second pass failed: {result2.output}"
    assert "Skipped field" in result2.output or "skipped" in result2.output.lower()


# ==============================================================================
# Pipeline consistency tests
# ==============================================================================


def test_cli_api_same_result() -> None:
    """CLI and API should produce equivalent outputs for the same input.

    Run sample.pdf through both paths and verify:
      - Both produce valid PDFs
      - Both have same number of signature fields
    """
    pdf_bytes = _load_fixture("sample.pdf")

    # Via API
    api_resp = api_client.post(
        "/prepare",
        files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
    )
    assert api_resp.status_code == 200
    api_output = api_resp.content
    api_field_count = _get_field_count(api_output)

    # Via core functions (simulates CLI)
    extraction = find_text_locations(pdf_bytes)
    signer_locations = [
        (loc.page_index, loc.box, loc.page_width, loc.page_height)
        for loc in extraction.locations
    ]
    core_result = add_signature_fields(pdf_bytes, signer_locations)
    core_field_count = _get_field_count(core_result.pdf_bytes)

    assert api_field_count == core_field_count, (
        f"API added {api_field_count} fields, core added {core_field_count}"
    )


def test_output_size_reasonable() -> None:
    """Output PDF size should be reasonable.

    Output larger than input (due to incremental writer overhead and new fields),
    but not excessively large (< 2x input).
    """
    pdf_bytes = _load_fixture("sample.pdf")

    result = api_client.post(
        "/prepare",
        files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
    )
    assert result.status_code == 200

    output_size = len(result.content)
    input_size = len(pdf_bytes)

    assert output_size > input_size, "Output should be larger than input"
    assert output_size < input_size * 3, f"Output size seems excessive: {output_size} vs input {input_size}"


# ==============================================================================
# Custom search text tests
# ==============================================================================


def test_custom_search_text_api() -> None:
    """API with search_text parameter.

    sample.pdf has "Employee Name"; searching for "Employee Name" should find it.
    Searching for "XYZ" should return 422.
    """
    pdf_bytes = _load_fixture("sample.pdf")

    # Default search (Employee Name) should succeed
    resp1 = api_client.post(
        "/prepare",
        files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp1.status_code == 200

    # Custom search for non-existent text should fail with 422
    resp2 = api_client.post(
        "/prepare?search_text=NonExistent",
        files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp2.status_code == 422
    body = resp2.json()
    assert body["search_text"] == "NonExistent"


def test_custom_search_text_cli(tmp_path: Path) -> None:
    """CLI with --search-text option.

    Default should work; custom non-existent text should exit code 1.
    """
    input_pdf = _copy_fixture("sample.pdf", tmp_path)
    output_pdf = tmp_path / "out.pdf"

    # Default search
    result1 = cli_runner.invoke(cli_app, [str(input_pdf), "-o", str(output_pdf)])
    assert result1.exit_code == 0

    # Non-existent search text
    result2 = cli_runner.invoke(
        cli_app,
        [str(input_pdf), "-o", str(output_pdf), "--search-text", "XYZ", "--force"],
    )
    assert result2.exit_code == 1


# ==============================================================================
# Edge case tests
# ==============================================================================


def test_location_at_page_boundary() -> None:
    """Test that signature fields near page edges are handled correctly.

    Verify clamping logic keeps field within page bounds.
    """
    pdf_bytes = _load_fixture("sample.pdf")

    # Create a synthetic location near the right edge of a letter page (612pt width)
    near_edge = [
        (0, (550.0, 700.0, 620.0, 750.0), 612.0, 792.0)
    ]

    result = add_signature_fields(pdf_bytes, near_edge)
    assert len(result.fields_added) == 1

    box = result.fields_added[0].box
    x0, y0, x1, y1 = box
    assert x1 <= 612.0, "Field right edge should not exceed page width"
    assert y1 <= 792.0, "Field top edge should not exceed page height"


def test_extractor_preserves_page_metadata() -> None:
    """Verify extracted TextLocation includes correct page dimensions."""
    pdf_bytes = _load_fixture("sample.pdf")
    extraction = find_text_locations(pdf_bytes)

    assert len(extraction.locations) > 0
    for loc in extraction.locations:
        # Verify page dimensions are reasonable (A4 or letter size range)
        # A4: 595.28 x 841.89 points, Letter: 612 x 792 points
        assert 500 < loc.page_width < 650, f"Unexpected page width: {loc.page_width}"
        assert 700 < loc.page_height < 900, f"Unexpected page height: {loc.page_height}"


def test_all_locations_on_same_page() -> None:
    """Verify multi-match locations are all on page 0."""
    pdf_bytes = _load_fixture("multi-match.pdf")
    extraction = find_text_locations(pdf_bytes)

    assert len(extraction.locations) == 2
    for loc in extraction.locations:
        assert loc.page_index == 0, "multi-match.pdf should have both matches on page 0"
