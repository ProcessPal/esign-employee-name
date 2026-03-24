# Red-Team Scope Review: PDF E-Sign Application Plan

**Date:** 2026-03-24
**Reviewer:** code-reviewer
**Status:** Complete
**Inputs:** Proposed 8-phase plan, researcher report, brainstormer report

---

## Executive Summary

The proposed plan is mostly sound but contains **two phases that violate YAGNI** (FastAPI and self-signed cert generator), **one dependency mismatch** with the brainstormer recommendation (pdfminer.six recommended but plan lists it alongside a different stack), and **unclear acceptance criteria** across all phases. Total estimated time (3h 5m) is reasonable for the scope, but only if trimmed to the minimum viable feature set.

---

## Findings

### [CRITICAL] Phase 6 (FastAPI API) is scope creep -- defer to post-MVP

**Problem:** The stated goal is "Accept PDF -> find text -> add field -> return PDF." This is fully achievable with a CLI. FastAPI adds ~30 min of implementation plus ongoing maintenance surface (CORS, file upload validation, error response schemas, streaming responses, temp file cleanup, async handling). The brainstormer report explicitly frames API as a thin wrapper over shared core, meaning it adds no architectural value to phase 1.

**Impact:** 30 minutes of work + ongoing complexity for a feature not in the core requirement. Also introduces `python-multipart`, `uvicorn`, and potentially `aiofiles` as dependencies.

**Recommendation:** Remove Phase 6 entirely from MVP. The CLI satisfies the requirement. If API is needed, it becomes Phase 1 of a follow-up plan after the core works end-to-end. This saves 30 min and reduces the dependency footprint by 3 packages.

---

### [CRITICAL] Phase 8 (self-signed certificate generator) is out of scope

**Problem:** The requirement says "add e-signature field" and "return e-signable document." This means placing an unsigned field -- NOT signing with a certificate. The brainstormer confirms: "Default behavior adds an empty signature field. Actual signing with a certificate is a separate optional step." A cert generator is only needed if actual signing is in scope, and it is not.

**Impact:** 15 minutes wasted on a utility that serves no MVP function. Also pulls in `cryptography` as a direct dependency (it may come transitively via pyHanko, but the generator code itself is unnecessary).

**Recommendation:** Remove Phase 8 entirely. If needed for testing, a pre-generated test cert pair (committed as fixtures) takes 30 seconds with `openssl` and requires no application code.

---

### [IMPORTANT] Dependency mismatch: Plan says pdfminer.six but stack lists PyMuPDF patterns

**Problem:** The brainstormer recommends Approach C (pdfminer.six) for coordinate safety (no Y-axis conversion needed). The proposed plan's Phase 2 says "PDF text extractor module (pdfminer.six)" which aligns. However, the stack line says "pdfminer.six + pyHanko + Typer + FastAPI + cryptography" but the researcher report's example code predominantly uses PyMuPDF (`fitz`) patterns. If the implementer follows researcher examples rather than the brainstormer recommendation, they will introduce coordinate conversion bugs.

**Impact:** The #1 risk identified by the brainstormer is coordinate system mismatch. Using pdfminer.six eliminates it; using PyMuPDF reintroduces it.

**Recommendation:** Explicitly lock the plan to pdfminer.six for text extraction. Remove any PyMuPDF references from implementation guidance. Add to Phase 2 acceptance criteria: "Coordinates returned in PDF-native bottom-left origin. No coordinate conversion in the pipeline."

---

### [IMPORTANT] All phases lack acceptance criteria

**Problem:** Every phase is described as a title + time estimate. None specify what "done" looks like. For example:
- Phase 2: "PDF text extractor module" -- what constitutes success? Finding text on page 1? Multi-page? Returning coordinates in which format? Handling "not found"?
- Phase 4: "Core orchestrator" -- what inputs/outputs? What error cases?

**Impact:** Without acceptance criteria, phases can expand or contract unpredictably. The implementer must make assumptions, which may not align with intent.

**Recommendation:** Add 2-3 bullet-point acceptance criteria per phase. Examples:
- Phase 2: "Given a PDF with 'Employee Name' on page N, returns list of (page_index, (x0, y0, x1, y1)) in PDF-native coords. Returns empty list if not found."
- Phase 3: "Given (page_index, box_coords), appends a named SigFieldSpec to the PDF. Output PDF opens without errors in a PDF viewer."
- Phase 4: "Given input PDF path/bytes, returns output PDF bytes with signature field(s). Raises descriptive error if text not found."

---

### [IMPORTANT] Phase 4 (orchestrator) may be unnecessary -- risk of over-engineering

**Problem:** The plan creates three layers: extractor (Phase 2), signer (Phase 3), and orchestrator (Phase 4). For a ~200-line application, an orchestrator layer may be premature abstraction. The brainstormer's core logic sketch shows the entire flow in one function (~20 lines).

**Impact:** 15 minutes of implementation for a module that may just be a 10-line function calling two other functions. Adds an import layer without clear value.

**Recommendation:** Merge Phase 4 into Phase 5 (CLI). The CLI command handler IS the orchestrator: it calls the extractor, then the signer, then writes output. If the code grows beyond one screen (~50 lines), extract an orchestrator then. YAGNI.

---

### [MODERATE] Phase ordering: Tests (Phase 7) come too late

**Problem:** Tests are the last functional phase. This means 5 phases of code are written before any automated validation. If Phase 2 (extractor) has a coordinate bug, it propagates through Phases 3-6 before being caught.

**Impact:** Late-discovered bugs require rework across multiple modules. Integration issues compound.

**Recommendation:** Move test fixture creation to Phase 1 (project setup). Write extractor tests alongside Phase 2, signer tests alongside Phase 3. This is not TDD overhead -- it is the minimum verification that coordinates are correct before building on top of them.

---

### [MODERATE] Phase 2 time estimate (30 min) may be tight for pdfminer.six

**Problem:** pdfminer.six has a verbose, low-level API requiring LAParams tuning, LTTextBox/LTTextLine traversal, and text assembly logic. The brainstormer notes "Manual layout traversal" as a con and estimates ~250 lines total. The researcher report's pdfminer section shows significantly more boilerplate than PyMuPDF.

**Impact:** Phase 2 may run 15-20 minutes over estimate, especially if LAParams need tuning for the target PDF format.

**Recommendation:** Keep the 30 min estimate but add a time-box rule: if LAParams tuning takes >15 min, use default params and document the limitation. Optimization is a follow-up task.

---

### [MODERATE] Missing error handling strategy

**Problem:** No phase addresses what happens when:
- Input is not a valid PDF (corrupted, password-protected, zero-byte)
- "Employee Name" text is not found in the document
- PDF has unusual structure (linearized, encrypted, XFA forms)
- Signature field name conflicts with existing fields

**Impact:** The application will crash with unhelpful tracebacks on edge cases.

**Recommendation:** Add error handling as an explicit acceptance criterion for Phase 4 (or wherever orchestration lives):
- Invalid PDF -> clear error message with exit code 1
- Text not found -> clear error message listing pages scanned
- Field name conflict -> auto-increment field name suffix

---

### [MODERATE] "Employee Name" search is too rigid

**Problem:** The plan hardcodes searching for "Employee Name" but does not address:
- Case sensitivity: "employee name" or "EMPLOYEE NAME"
- Whitespace: "Employee  Name" (double space) or "EmployeeName"
- Surrounding context: "Employee Name:" vs "Employee Name" vs "Employee Name _________"

**Impact:** The tool will fail silently on PDFs with minor text variations.

**Recommendation:** Phase 2 should use case-insensitive matching and handle whitespace normalization. This is not scope creep -- it is robustness for the stated requirement. A simple `re.search(r"employee\s+name", text, re.IGNORECASE)` covers the common cases.

---

### [LOW] Typer may be heavier than needed for a single command

**Problem:** The CLI has one command: process a PDF. Typer adds a dependency for what could be `argparse` (stdlib) in ~10 lines.

**Impact:** Minimal -- Typer is lightweight. But it is a dependency that serves no purpose beyond argument parsing for a single command.

**Recommendation:** Accept Typer if the team prefers it for DX, but `argparse` is a zero-dependency alternative. Not worth changing if already decided.

---

## Minimum Viable Scope (Recommended)

| Phase | Description | Time | Status |
|-------|-------------|------|--------|
| 1 | Project setup: pyproject.toml, src layout, test fixture PDF | 15 min | Keep |
| 2 | Text extractor (pdfminer.six): find "Employee Name", return PDF-native coords + unit test | 35 min | Keep (expanded) |
| 3 | Signature field placer (pyHanko): accept coords, append SigFieldSpec + unit test | 30 min | Keep |
| 4 | CLI (Typer): wire extractor + placer, error handling, output file | 25 min | Keep (merged with old Phase 4) |
| 5 | Integration test with fixture PDF | 15 min | Keep (moved from Phase 7) |

**Total: ~2 hours** (down from 3h 5m)

### Removed from MVP
- ~~Phase 6: FastAPI API~~ -- YAGNI, add when web interface is needed
- ~~Phase 8: Self-signed cert generator~~ -- Out of scope (field-only, not signing)

### Deferred to Follow-up
- FastAPI wrapper (thin layer over core, ~20 min when needed)
- Configurable search patterns (regex support beyond "Employee Name")
- Batch processing mode
- PDF/A compliance validation

---

## Scope Creep Watchlist

These items from the risk areas are correctly identified. Reaffirming they must NOT enter the plan:

1. **Actual PDF signing** -- The tool places fields, not signatures. No certs needed.
2. **OCR for scanned PDFs** -- Massive scope increase (Tesseract dependency, image processing). Hard no.
3. **Web UI** -- Not even an API is needed for MVP. UI is multiple sprints away.
4. **Configurable search patterns** -- "Employee Name" is the requirement. Regex support is follow-up.
5. **Multi-page report generation** -- Not in any requirement.
6. **PDF/A compliance** -- Not in any requirement.
7. **TextLocator protocol/ABC** -- The brainstormer suggests this abstraction, but for a single extractor implementation, an ABC is premature. YAGNI. A plain function is sufficient; extract an interface only when a second implementation exists.

---

## Unresolved Questions

1. **Is there a sample PDF available?** Without a real target document, the implementer will need to create a test fixture that may not match production PDF structure. This is the single biggest risk to Phase 2 accuracy.

2. **Should the signature field be placed ON the text or BELOW it?** "At the Employee Name location" is ambiguous -- does the field overlay the text, appear directly below it, or replace it? This affects box coordinate calculation.

3. **What is the expected signature field size?** The brainstormer suggests text bbox + padding, but a signature field typically needs to be larger than the text it replaces (e.g., 200x50 points). The plan should specify dimensions.

4. **Single or multiple occurrences?** If "Employee Name" appears 3 times in a document, should there be 3 signature fields or just the first one?
