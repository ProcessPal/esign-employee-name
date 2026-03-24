# Plan: eSign Employee Name PDF Application

**Goal:** Build a complete Python application that accepts a PDF, finds "Employee Name" text, places a pyHanko signature field at that location, and returns the e-signable document.
**Stack:** pdfminer.six + pyHanko + Typer (CLI) + FastAPI (API)
**Approach:** C (pdfminer.six) — native PDF coordinate system, no conversion bugs

## Phases

| Phase | Description | Files | Depends |
|-------|-------------|-------|---------|
| 01 | Project setup + test fixtures | pyproject.toml, src/esign/__init__.py, tests/fixtures/ | — |
| 02 | Text extractor (pdfminer.six) | src/esign/extractor.py, tests/test_extractor.py | 01 |
| 03 | Signature field placer (pyHanko) | src/esign/signer.py, tests/test_signer.py | 01 |
| 04 | CLI interface (Typer) | src/esign/cli.py, tests/test_cli.py | 02, 03 |
| 05 | FastAPI interface | src/esign/api.py, tests/test_api.py | 02, 03 |
| 06 | Integration testing + validation | tests/test_integration.py | 04, 05 |

## Key Decisions (from red-team)
- **pdfminer.six only** — no PyMuPDF, no coordinate conversion
- **Recursive traversal** — handle LTTextLine at any nesting depth (I1)
- **Case-insensitive + whitespace-normalized** search via regex
- **BytesIO processing** — no temp files, eliminates cleanup race (C3)
- **Existing field detection** — check for duplicate names, skip if exists (C5)
- **Existing signature check** — warn/refuse if cert-locked PDF (C4)
- **Box clamping** — clamp padded box to page dimensions (I6)
- **Sync endpoints** — use `def` not `async def` for FastAPI (M2)
- **Upload validation** — 50MB limit, PDF magic bytes check (C2)
- **Field-only mode** — no actual signing, just empty signature fields
