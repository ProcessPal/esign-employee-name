"""PDF text location extractor using pdfminer.six."""

from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO

from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTTextLine
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfminer.pdfparser import PDFSyntaxError


@dataclass
class TextLocation:
    page_index: int
    box: tuple[float, float, float, float]  # (x0, y0, x1, y1) PDF-native bottom-left coords
    page_width: float
    page_height: float


@dataclass
class ExtractionResult:
    locations: list[TextLocation]
    pages_scanned: int


_SEARCH_PATTERN = re.compile(r"employee\s+name", re.IGNORECASE)


def _iter_text_lines(element: object):
    """Recursively yield all LTTextLine elements at any nesting depth."""
    if isinstance(element, LTTextLine):
        yield element
    if hasattr(element, "__iter__"):
        for child in element:
            yield from _iter_text_lines(child)


def find_text_locations(
    pdf_bytes: bytes,
    search_text: str = "Employee Name",
) -> list[TextLocation]:
    """Find all occurrences of search_text in PDF, return their page and coordinates.

    Args:
        pdf_bytes: Raw PDF file content.
        search_text: Text to search for (default "Employee Name").

    Returns:
        List of TextLocation for each match found.

    Raises:
        ValueError: If PDF is encrypted or malformed, or bytes are empty/invalid.
    """
    if not pdf_bytes:
        raise ValueError("Invalid PDF")

    # Build pattern from search_text: case-insensitive, whitespace-normalized
    words = search_text.strip().split()
    if words:
        pattern = re.compile(r"\s+".join(re.escape(w) for w in words), re.IGNORECASE)
    else:
        pattern = _SEARCH_PATTERN

    results: list[TextLocation] = []
    pages_scanned = 0

    try:
        pages = extract_pages(BytesIO(pdf_bytes), laparams=LAParams())
        for page_index, page_layout in enumerate(pages):
            pages_scanned += 1
            page_width = page_layout.width
            page_height = page_layout.height
            for line in _iter_text_lines(page_layout):
                line_text = line.get_text()
                if pattern.search(line_text):
                    x0, y0, x1, y1 = line.bbox
                    results.append(
                        TextLocation(
                            page_index=page_index,
                            box=(x0, y0, x1, y1),
                            page_width=page_width,
                            page_height=page_height,
                        )
                    )
    except PDFPasswordIncorrect:
        raise ValueError("PDF is encrypted")
    except PDFSyntaxError:
        raise ValueError("Invalid PDF")

    return ExtractionResult(locations=results, pages_scanned=pages_scanned)
