# Phase 01: Project Setup + Test Fixtures

## Files
- `pyproject.toml` — dependencies, project metadata, entry points
- `src/esign/__init__.py` — package init
- `tests/__init__.py`
- `tests/conftest.py` — shared fixtures
- `tests/fixtures/create_test_pdf.py` — script to generate test PDFs
- `tests/fixtures/sample.pdf` — generated test PDF with "Employee Name"

## Acceptance Criteria
- `pip install -e .` succeeds
- `python -c "import esign"` works
- Test fixture PDF exists with "Employee Name" at a known location
- Project structure matches src layout

## Dependencies (pyproject.toml)
- pyhanko >= 0.25
- pdfminer.six >= 20231228
- typer >= 0.12
- fastapi >= 0.115
- uvicorn >= 0.30
- python-multipart >= 0.0.18

## Dev Dependencies
- pytest >= 8.0
- httpx >= 0.27 (for FastAPI test client)
- fpdf2 >= 2.8 (for generating test PDFs)
