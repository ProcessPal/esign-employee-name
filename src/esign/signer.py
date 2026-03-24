"""Signature field placement using pyHanko incremental PDF writer."""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO

from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign.fields import SigFieldSpec, append_signature_field


@dataclass
class SignatureFieldResult:
    field_name: str
    page_index: int
    box: tuple[float, float, float, float]


@dataclass
class PrepareResult:
    pdf_bytes: bytes
    fields_added: list[SignatureFieldResult] = field(default_factory=list)
    fields_skipped: list[str] = field(default_factory=list)


def _get_existing_field_names(writer: IncrementalPdfFileWriter) -> set[str]:
    """Return the set of existing AcroForm field names from the writer's base reader."""
    reader = writer.prev
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


def _compute_box(
    raw_box: tuple[float, float, float, float],
    page_width: float,
    page_height: float,
    padding: float,
    min_width: float,
    min_height: float,
) -> tuple[float, float, float, float]:
    """Apply padding, enforce minimums, and clamp to page bounds."""
    x0, y0, x1, y1 = raw_box

    # Add padding on all sides
    x0 -= padding
    y0 -= padding
    x1 += padding
    y1 += padding

    # Enforce minimum width (center-expand)
    width = x1 - x0
    if width < min_width:
        cx = (x0 + x1) / 2.0
        x0 = cx - min_width / 2.0
        x1 = cx + min_width / 2.0

    # Enforce minimum height (expand downward)
    height = y1 - y0
    if height < min_height:
        y0 = y1 - min_height

    # Clamp to page dimensions
    x0 = max(0.0, x0)
    y0 = max(0.0, y0)
    x1 = min(page_width, x1)
    y1 = min(page_height, y1)

    return (x0, y0, x1, y1)


def add_signature_fields(
    pdf_bytes: bytes,
    locations: list[tuple[int, tuple[float, float, float, float], float, float]],
    field_name_prefix: str = "EmployeeSig",
    padding: float = 10.0,
    min_width: float = 200.0,
    min_height: float = 50.0,
) -> PrepareResult:
    """Add signature fields to a PDF at the specified locations.

    Args:
        pdf_bytes: Raw PDF bytes to process.
        locations: List of (page_index, (x0, y0, x1, y1), page_width, page_height).
        field_name_prefix: Prefix for generated field names.
        padding: Points to add around each bounding box.
        min_width: Minimum field width in points.
        min_height: Minimum field height in points.

    Returns:
        PrepareResult with output PDF bytes and lists of added/skipped fields.

    Raises:
        ValueError: If the input bytes are not a valid PDF.
    """
    if not locations:
        return PrepareResult(pdf_bytes=pdf_bytes)

    try:
        writer = IncrementalPdfFileWriter(BytesIO(pdf_bytes))
    except Exception as exc:
        raise ValueError("Cannot process PDF") from exc

    existing_names = _get_existing_field_names(writer)
    fields_added: list[SignatureFieldResult] = []
    fields_skipped: list[str] = []

    for index, (page_index, raw_box, page_width, page_height) in enumerate(locations):
        field_name = f"{field_name_prefix}_p{page_index}_{index}"

        if field_name in existing_names:
            fields_skipped.append(field_name)
            continue

        box = _compute_box(raw_box, page_width, page_height, padding, min_width, min_height)
        spec = SigFieldSpec(
            sig_field_name=field_name,
            on_page=page_index,
            box=box,
        )
        append_signature_field(writer, spec)
        fields_added.append(SignatureFieldResult(field_name=field_name, page_index=page_index, box=box))

    out = BytesIO()
    writer.write(out)
    return PrepareResult(pdf_bytes=out.getvalue(), fields_added=fields_added, fields_skipped=fields_skipped)
