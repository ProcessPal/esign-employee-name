# Phase 04: CLI Interface (Typer)

## Files
- `src/esign/cli.py` — Typer app with `prepare` command
- `tests/test_cli.py` — CLI integration tests

## Acceptance Criteria
- `esign prepare input.pdf -o output.pdf` works end-to-end
- `esign prepare input.pdf` outputs to `input_prepared.pdf` by default
- `--search-text` flag allows overriding default "Employee Name"
- Exit code 0 on success, 1 on text-not-found, 2 on invalid PDF
- Stdout reports: pages scanned, fields added, field locations
- Input validation: file exists, has .pdf extension or PDF magic bytes
- `--force` flag to overwrite existing output file

## Key Implementation Details
- CLI is the orchestrator: calls extractor.find_text_locations() then signer.add_signature_fields()
- Reads input as bytes, passes BytesIO through pipeline
- Structured output messages (not raw exceptions)
