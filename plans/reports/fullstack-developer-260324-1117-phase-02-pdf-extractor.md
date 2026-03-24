## Phase Implementation Report

### Executed Phase
- Phase: Phase 02 — PDF Text Extractor
- Plan: none (direct task)
- Status: completed

### Files Modified
- `src/esign/extractor.py` — created, 79 lines
- `tests/test_extractor.py` — created, 71 lines

### Tasks Completed
- [x] `TextLocation` dataclass with `page_index`, `box`, `page_width`, `page_height`
- [x] `find_text_locations(pdf_bytes, search_text)` using `pdfminer.high_level.extract_pages`
- [x] Recursive `_iter_text_lines()` generator handles arbitrary nesting depth
- [x] Case-insensitive + whitespace-normalized matching via `re.IGNORECASE`
- [x] PDF-native coords returned as-is (no conversion)
- [x] `BytesIO` wrapping for bytes input
- [x] Encrypted PDF → `ValueError("PDF is encrypted")` via `PDFPasswordIncorrect`
- [x] Malformed/empty PDF → `ValueError("Invalid PDF")` via `PDFSyntaxError` + empty check
- [x] 7 tests covering: single match, no match, multi-match, case-insensitivity, coord bounds, invalid bytes, empty bytes

### Tests Status
- Type check: n/a (no mypy configured)
- Unit tests: 7/7 passed (0.08s)

### Issues Encountered
None.

### Next Steps
- Phase 03 (signature field injector) can now import `TextLocation` and `find_text_locations` from `esign.extractor`
