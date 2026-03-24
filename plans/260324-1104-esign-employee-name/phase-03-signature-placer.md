# Phase 03: Signature Field Placer (pyHanko)

## Files
- `src/esign/signer.py` — add_signature_fields() function
- `tests/test_signer.py` — unit tests

## Acceptance Criteria
- Given PDF bytes + list of (page, box) locations, appends named SigFieldSpec fields
- Output PDF opens without errors in a PDF viewer
- Existing signature fields are detected; duplicates skipped with warning
- Field names use format: `EmployeeSig_p{page}_{index}`
- Box coordinates clamped to page dimensions (no off-page fields)
- Padding: 10pt on each side of text bbox, min field size 200x50pt
- Handles PDFs with existing AcroForm fields without corruption
- Checks for certification signatures (MDP restrictions) — refuses if locked

## Key Implementation Details
- `IncrementalPdfFileWriter` with `BytesIO` input (no temp files)
- `append_signature_field()` with `SigFieldSpec(sig_field_name, on_page, box)`
- Write to new `BytesIO` output, never in-place
- Enumerate existing field names before adding
