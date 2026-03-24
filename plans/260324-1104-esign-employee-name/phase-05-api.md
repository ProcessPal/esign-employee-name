# Phase 05: FastAPI Interface

## Files
- `src/esign/api.py` — FastAPI app with /prepare endpoint
- `tests/test_api.py` — API tests with httpx TestClient

## Acceptance Criteria
- `POST /prepare` accepts PDF upload, returns modified PDF
- Upload validation: 50MB max, PDF magic bytes (`%PDF-`), content-type check
- Returns 200 + PDF on success
- Returns 422 + JSON error on text-not-found
- Returns 400 + JSON error on invalid/encrypted PDF
- Returns 413 on file too large
- `GET /health` returns 200
- All processing via BytesIO (no temp files)
- Sync endpoint (`def` not `async def`) to avoid blocking event loop

## Key Implementation Details
- `from esign.extractor import find_text_locations`
- `from esign.signer import add_signature_fields`
- `StreamingResponse` with `BytesIO` output
- Content-Disposition header for download filename
- Optional `search_text` query parameter
