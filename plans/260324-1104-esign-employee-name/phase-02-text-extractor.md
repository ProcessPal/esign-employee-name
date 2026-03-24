# Phase 02: Text Extractor (pdfminer.six)

## Files
- `src/esign/extractor.py` — find_text_locations() function
- `tests/test_extractor.py` — unit tests

## Acceptance Criteria
- Given a PDF with "Employee Name" on page N, returns list of `(page_index, (x0, y0, x1, y1))` in PDF-native bottom-left coords
- Returns empty list if text not found
- Case-insensitive: finds "EMPLOYEE NAME", "employee name", "Employee Name"
- Whitespace-normalized: handles "Employee  Name" (double space)
- Recursive traversal: finds text at any nesting depth (LTTextLine under LTPage or LTTextBox)
- Handles encrypted PDFs gracefully (raises descriptive error)
- All coordinates validated to fall within page dimensions

## Key Implementation Details
- Use `pdfminer.high_level.extract_pages()` with default `LAParams`
- Recursive generator to walk all `LTText*` elements
- `re.search(r"employee\s+name", text, re.IGNORECASE)` for matching
- Return page mediabox dimensions alongside text coordinates for downstream validation
