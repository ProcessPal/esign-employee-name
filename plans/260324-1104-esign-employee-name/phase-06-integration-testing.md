# Phase 06: Integration Testing + Validation

## Files
- `tests/test_integration.py` — end-to-end tests

## Acceptance Criteria
- CLI: input fixture PDF -> output has signature fields at correct coordinates
- API: upload fixture PDF -> response PDF has signature fields
- Verify output PDF opens in a PDF reader without errors
- Verify signature field is at expected coordinates (within 5pt tolerance)
- Test: "Employee Name" not found -> appropriate error
- Test: non-PDF file -> appropriate error
- Test: empty file -> appropriate error
- Test: PDF with existing form fields -> fields preserved
- Test: multiple "Employee Name" occurrences -> multiple signature fields
