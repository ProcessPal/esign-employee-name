# Red-Team Analysis: PDF E-Signing Implementation Plan (Approach C)

**Date:** 2026-03-24
**Reviewer:** code-reviewer
**Scope:** Proposed plan -- pdfminer.six + pyHanko + Typer/FastAPI hybrid
**Status:** Complete

---

## Executive Summary

The plan is sound in its core architectural choice (pdfminer.six for native coordinate alignment with pyHanko), but has **5 critical**, **7 important**, and **8 moderate** gaps that must be addressed before implementation. The most dangerous blindspots are: (1) pdfminer.six silently returning wrong coordinates on rotated/cropped pages, which the plan assumes away by claiming "no conversion needed"; (2) unrestricted file upload creating a denial-of-service surface; and (3) no handling of the case where `IncrementalPdfFileWriter` corrupts PDFs that already contain AcroForm fields or existing signatures.

**Finding count:** 20 total (5 critical, 7 important, 8 moderate)

---

## Critical Findings

### [CRITICAL] C1: Rotated Pages Break the "No Conversion Needed" Assumption

**Description:** The plan's primary selling point is that pdfminer.six coordinates natively match pyHanko's bottom-left origin, eliminating coordinate conversion. This is only true for unrotated pages with no CropBox offset. PDF pages can have a `/Rotate` attribute (90, 180, 270) and a CropBox that differs from MediaBox. pdfminer.six applies the rotation matrix to character bounding boxes, but the resulting coordinates may not align with what pyHanko expects for signature field placement on the *visual* page. Furthermore, pdfminer.six issue [#454](https://github.com/pdfminer/pdfminer.six/issues/454) documents that bounding boxes on rotated characters can collapse to near-zero area, and pyHanko discussion [#150](https://github.com/MatthiasValvekens/pyHanko/discussions/150) confirms signature placement on rotated pages requires explicit handling.

**Impact:** Signature fields placed off-page, at wrong locations, or with zero-area boxes on any PDF with page rotation. This is a silent data-integrity failure -- no error raised, just wrong output.

**Mitigation:**
1. Read the page's `/Rotate` value and CropBox from the PDF dictionary before text extraction.
2. If `/Rotate != 0` or CropBox != MediaBox, apply an explicit coordinate transform.
3. Add a validation step: assert that the computed signature box falls within the page's visible area (CropBox or MediaBox).
4. Include rotated-page test fixtures (90, 180, 270) in the test suite.

---

### [CRITICAL] C2: Unrestricted File Upload -- No Size Limit, No Content Validation

**Description:** The plan's FastAPI endpoint (`POST /prepare`) accepts a file upload with no documented size limit, no magic-byte validation, and no filename sanitization. FastAPI's `UploadFile` reads the entire file into memory by default for small files and spools to disk for larger ones, but the threshold and cleanup are not addressed. Additionally, [CVE-2024-24762](https://security.snyk.io/vuln/SNYK-PYTHON-FASTAPI-6228055) and [CVE-2026-28356](https://dailycve.com/multipart-python-library-redos-cve-2026-28356-high/) demonstrate that `python-multipart` (a FastAPI dependency) has had ReDoS vulnerabilities in Content-Type header parsing.

**Impact:** Denial-of-service via large file uploads (memory exhaustion), crafted Content-Type headers (CPU exhaustion), or zip-bomb-style PDFs that expand during parsing.

**Mitigation:**
1. Enforce a maximum upload size (e.g., 50 MB) at the ASGI/reverse-proxy level, not just in application code.
2. Validate PDF magic bytes (`%PDF-`) before passing to pdfminer.six.
3. Pin `python-multipart >= 1.2.2` (or `multipart >= 1.3.1`) to avoid known ReDoS.
4. Set a timeout on the extraction step to kill runaway parses.
5. Never use the client-supplied filename for filesystem operations.

---

### [CRITICAL] C3: No Temp File Cleanup on Error Paths

**Description:** The research report's FastAPI example shows `os.unlink(temp_path)` in a `finally` block after `FileResponse`, but `FileResponse` is a streaming response -- the file is read *after* the handler returns. This means the `finally` block deletes the file before FastAPI finishes sending it. Meanwhile, if the processing step raises an exception, temp files are leaked. The plan does not address this race condition or propose a cleanup strategy.

**Impact:** (a) Broken downloads when temp file is deleted before streaming completes. (b) Disk exhaustion from leaked temp files under error conditions. (c) Potential information disclosure if temp files contain sensitive PDF content and are world-readable.

**Mitigation:**
1. Use `BytesIO` for in-memory processing (field-only mode produces small incremental appends) instead of temp files. Eliminates the problem entirely.
2. If temp files are needed for large PDFs, use `BackgroundTask` cleanup: `return FileResponse(path, background=BackgroundTask(os.unlink, path))`.
3. Set temp directory permissions to `0o700`.
4. Implement a periodic cleanup job for orphaned temp files older than N minutes.

---

### [CRITICAL] C4: Existing AcroForm Fields and Signatures Can Be Corrupted

**Description:** The plan assumes PDFs are simple text documents, but real-world employee forms commonly contain existing AcroForm fields (text inputs, checkboxes, radio buttons) and may already have signatures. `IncrementalPdfFileWriter` + `append_signature_field` modifies the AcroForm dictionary. If the PDF already has an AcroForm with `/NeedAppearances` set, or if it contains existing signature fields with seed values or certification signatures (MDP level 1 -- no changes allowed), appending a new field can either: (a) corrupt the existing form structure, (b) invalidate existing signatures, or (c) raise an opaque error from pyHanko.

**Impact:** Silently invalidating existing digital signatures on incoming PDFs. Destroying existing form field data. Producing PDFs that Adobe Reader/Acrobat flags as "modified after signing."

**Mitigation:**
1. Before modifying, check for existing signatures: read the PDF's `/AcroForm` dictionary and check for any `/Sig` type fields.
2. If a certification signature exists with MDP restrictions, refuse to modify and return a descriptive error.
3. If non-certification signatures exist, warn the user that adding fields will invalidate them.
4. Add integration tests with pre-signed PDFs and PDFs containing existing form fields.

---

### [CRITICAL] C5: Duplicate Signature Field Names on Reprocessed PDFs

**Description:** The plan names fields `EmployeeSig_0`, `EmployeeSig_1`, etc., using a simple index. If the same PDF is processed twice (e.g., user uploads, downloads, then re-uploads), the second pass will attempt to create fields with names that already exist. The pyHanko documentation does not specify behavior for duplicate `sig_field_name` values -- it may silently overwrite, raise an exception, or create a malformed AcroForm with duplicate entries.

**Impact:** PDF corruption, duplicate fields in the AcroForm, or unhandled exceptions crashing the API.

**Mitigation:**
1. Before adding fields, enumerate existing signature field names in the PDF.
2. Use a naming scheme that includes a hash or UUID suffix: `EmployeeSig_{page}_{hash(box_coords)}`.
3. If a field with the target name already exists at the target location, skip it and report as already-processed.
4. Add a `--force` flag to allow re-processing (removes existing fields first).

---

## Important Findings

### [IMPORTANT] I1: pdfminer.six LTTextLine Appearing Directly Under LTPage

**Description:** The proposed extractor code iterates `LTPage -> LTTextBox -> LTTextLine`. However, pdfminer.six [issue #763](https://github.com/pdfminer/pdfminer.six/issues/763) documents that `LTTextLineHorizontal` objects can appear directly under `LTPage` (not nested in `LTTextBox`), particularly for whitespace-only lines. While "Employee Name" itself is unlikely to be whitespace, this demonstrates that the assumed hierarchy is not guaranteed. Other PDFs with unusual structure may place text lines at the page level.

**Impact:** Missed "Employee Name" occurrences in some PDFs, producing a false "not found" result with no indication that text was skipped.

**Mitigation:**
1. Use a recursive traversal that handles all `LTText*` types at any nesting depth, not a fixed two-level iteration.
2. Example: `def find_text(element): if hasattr(element, '__iter__'): for child in element: yield from find_text(child)`.

---

### [IMPORTANT] I2: "Employee Name" Split Across Text Elements

**Description:** The plan searches for `"Employee Name" in text` within a single `LTTextLine.get_text()`. This works when both words are in the same text line. However, PDFs can render "Employee" and "Name" as separate text operations (different font, different text matrix), causing pdfminer.six to place them in separate `LTTextBox` or `LTTextLine` elements. This is common in: (a) table cells where each cell is a separate text block, (b) PDFs generated from Word/HTML where bolding changes mid-phrase, (c) PDFs with justified text causing large word gaps.

**Impact:** "Employee Name" not detected even though it's visually present on the page.

**Mitigation:**
1. Implement a two-pass strategy: first try line-level matching, then fall back to character-level spatial matching.
2. For spatial matching: find all "Employee" text boxes, then check if a "Name" text box exists within a configurable horizontal proximity (e.g., 30 points) and similar Y position (within 5 points).
3. Log the raw extracted text structure when no match is found, so users can debug.

---

### [IMPORTANT] I3: Variable Page Sizes Cause Wrong Coordinates

**Description:** pdfminer.six [issue #702](https://github.com/pdfminer/pdfminer.six/issues/702) documents that in PDFs with pages of different sizes, coordinates on later pages can be incorrect. The library may cache or reuse coordinate transformation data from earlier pages.

**Impact:** Signature field placed at wrong position on pages that differ in size from the first page. This is a known open bug with no upstream fix.

**Mitigation:**
1. After extraction, validate that all coordinates fall within the page's declared dimensions.
2. Add test fixtures with mixed page sizes (Letter + Legal, A4 + A3).
3. Consider extracting only the specific page containing "Employee Name" rather than all pages, to avoid the multi-page-size bug path.
4. Document this as a known limitation.

---

### [IMPORTANT] I4: No Graceful Handling of pdfminer.six Parse Failures

**Description:** The plan specifies HTTP 422 / exit code 1 only for "Employee Name not found." pdfminer.six can fail in multiple other ways: `PDFSyntaxError` for malformed PDFs, `PSEOF` for truncated files, `PDFEncryptionError` for password-protected PDFs, and silent infinite loops on certain malformed content streams ([issue #231](https://github.com/pdfminer/pdfminer.six/issues/231) -- rotated text causing interpreter to run indefinitely).

**Impact:** Unhandled exceptions returning HTTP 500 with stack traces (information disclosure). Hung worker processes on malformed PDFs (resource exhaustion).

**Mitigation:**
1. Wrap all pdfminer.six calls in try/except catching `PDFSyntaxError`, `PDFEncryptionError`, `PSEOF`, and a generic `Exception`.
2. Return structured error responses: 422 for "not found," 400 for "invalid/encrypted PDF," 500 for unexpected errors (without stack trace).
3. Run extraction in a subprocess or thread with a hard timeout (e.g., 30 seconds) to kill hung parses.
4. Check for encryption before attempting extraction: read the PDF trailer for `/Encrypt`.

---

### [IMPORTANT] I5: IncrementalPdfFileWriter Requires Seekable Input Stream

**Description:** The `IncrementalPdfFileWriter` requires its input to be both readable and seekable. If the API endpoint reads the upload into a non-seekable stream, or if `BytesIO(pdf_bytes)` is not rewound after reading, pyHanko will raise an error or produce corrupt output. The plan's code sketch creates `BytesIO(pdf_bytes)` (which is seekable at position 0), but the FastAPI upload path needs `await file.read()` first, and the ordering and buffer management are not specified.

**Impact:** Runtime errors or silently corrupt PDFs when the buffer state is wrong.

**Mitigation:**
1. Always create a fresh `BytesIO(content)` from the raw bytes, never reuse the upload stream.
2. After `w.write(output)`, call `output.seek(0)` before returning.
3. Add an assertion: `assert buf.seekable()` before passing to `IncrementalPdfFileWriter`.

---

### [IMPORTANT] I6: Signature Box Sizing -- Padding Can Push Box Off-Page

**Description:** The plan adds 5-10pt padding to the text bounding box. If "Employee Name" appears near a page edge (common in headers, footers, or margin labels), the padded box can extend beyond the page boundary. pyHanko does not validate that the box fits within the page.

**Impact:** Signature field partially or fully off-page, invisible in PDF viewers, unable to be signed.

**Mitigation:**
1. Clamp the padded box to the page dimensions: `x0 = max(0, x0 - padding)`, `x1 = min(page_width, x1 + padding)`, etc.
2. If clamping reduces the box below a minimum viable size (e.g., 50x20 points), log a warning and use a fixed-size box centered on the text.

---

### [IMPORTANT] I7: No Input Validation on CLI Path Arguments

**Description:** The Typer CLI accepts `input_pdf: Path` and `output_pdf: Path`. Without validation, this allows: (a) reading arbitrary files (if the user passes a non-PDF path, pdfminer.six will attempt to parse it), (b) overwriting arbitrary files (output path), (c) writing to sensitive locations.

**Impact:** While this is a CLI tool (user has local access anyway), in scripted/CI environments, unsanitized path arguments can cause data loss if output overwrites an important file.

**Mitigation:**
1. Validate input file exists and has `.pdf` extension (or check magic bytes).
2. Warn (or refuse with `--force`) if output file already exists.
3. Validate output directory exists and is writable.

---

## Moderate Findings

### [MODERATE] M1: LAParams Defaults May Miss Text in Real-World PDFs

**Description:** The plan acknowledges LAParams tuning as a risk but proposes `word_margin=0.2` without justification. The default `word_margin` in pdfminer.six is `0.1`. Different PDF generators (Word, LaTeX, InDesign, Chrome print-to-PDF) produce wildly different character spacing. A `word_margin` that works for one generator may merge "Employee Name" with adjacent text or split it into separate elements for another.

**Mitigation:**
1. Test with PDFs from at least 5 different generators (Word, Google Docs, Chrome print, LaTeX, Adobe InDesign).
2. Expose LAParams as optional configuration (CLI flags / API query params) for edge cases.
3. Default to pdfminer.six's own defaults rather than overriding unless testing proves a specific value is better.

---

### [MODERATE] M2: No Concurrency Safety in FastAPI Endpoint

**Description:** Both pdfminer.six and pyHanko are synchronous libraries. The FastAPI endpoint is declared `async def` but calls synchronous blocking code. This blocks the event loop, preventing other requests from being served during the 2-3 second extraction.

**Mitigation:**
1. Either use `def` (not `async def`) for the endpoint so FastAPI runs it in a thread pool automatically.
2. Or use `run_in_executor` to offload the blocking work to a thread pool.
3. Set a worker count appropriate for the expected concurrency (`uvicorn --workers N`).

---

### [MODERATE] M3: python-multipart Dependency Not Pinned

**Description:** FastAPI requires `python-multipart` for file uploads, but the plan does not include it in the dependency list. Furthermore, `python-multipart` was superseded by `multipart` in newer versions, and version confusion between the two packages has caused breakage. The known CVE-2026-28356 (ReDoS, CVSS 7.5) affects `multipart <= 1.3.0`.

**Mitigation:**
1. Explicitly declare `python-multipart >= 0.0.18` or `multipart >= 1.3.1` in `pyproject.toml`.
2. Add a CI step that checks for known CVEs in dependencies (e.g., `pip-audit`).

---

### [MODERATE] M4: No Logging or Observability

**Description:** The plan includes no mention of logging. For a tool that processes arbitrary user-uploaded PDFs, the absence of logging means: no way to debug extraction failures, no audit trail of processed documents, no performance monitoring.

**Mitigation:**
1. Add structured logging (Python `logging` module with JSON formatter).
2. Log: input file hash (not content), page count, extraction duration, field count, errors.
3. Never log PDF content or personally identifiable information.

---

### [MODERATE] M5: Test Strategy Gaps

**Description:** The plan lists four test files but no specifics on what they test. Key gaps:
- No test for encrypted/password-protected PDFs
- No test for PDFs with existing signatures or form fields
- No test for rotated pages (90/180/270)
- No test for mixed page sizes
- No test for "Employee Name" appearing in headers/footers/watermarks
- No test for PDFs where "Employee Name" is in an image (to verify graceful failure)
- No negative test for non-PDF files
- No fuzz testing consideration

**Mitigation:**
1. Create a test fixture matrix covering the cases above.
2. Use `reportlab` or `fpdf2` to programmatically generate test PDFs with known text positions for deterministic assertion.
3. Add a property-based test: for any generated PDF with "Employee Name" at known coordinates, the output signature field box must contain those coordinates.

---

### [MODERATE] M6: pyHanko Version Compatibility Not Specified

**Description:** The plan references pyHanko API patterns but does not pin a version. pyHanko has had breaking changes between major versions (e.g., `SigFieldSpec` gained `empty_field_appearance` in 0.8.0, writer class hierarchy changed). The plan references `IncrementalPdfFileWriter` from `pyhanko.pdf_utils.incremental_writer`, which is the current import path but has changed locations in past versions.

**Mitigation:**
1. Pin pyHanko to a specific major version range in `pyproject.toml` (e.g., `pyhanko >= 0.25, < 1.0`).
2. Pin pdfminer.six version as well to avoid upstream regressions.
3. Add a version compatibility check at import time.

---

### [MODERATE] M7: No CORS Configuration for API

**Description:** If the FastAPI API is consumed by a browser-based frontend, CORS headers are required. The plan mentions a "web upload" use case but does not address CORS.

**Mitigation:**
1. Add FastAPI CORS middleware with explicit allowed origins (not `*`).
2. If API is internal-only, document that and consider not exposing it on public interfaces.

---

### [MODERATE] M8: Single-Threaded PDF Processing Creates Bottleneck

**Description:** At 2-3 seconds per PDF, a single-worker deployment can only handle ~20-30 PDFs per minute. The plan mentions performance as acceptable but does not address scaling.

**Mitigation:**
1. Document the throughput ceiling and recommended worker count.
2. For batch use cases, consider accepting multiple files in one request or providing a batch CLI mode.
3. Profile whether the bottleneck is pdfminer.six extraction or pyHanko writing, to know what to optimize first.

---

## Impossible Dependencies / Logical Contradictions

### Plan Claims pdfminer.six Is a Transitive Dependency of pyHanko

This was true historically but should be verified for the pinned version. pyHanko's `pyhanko-certvalidator` does not depend on pdfminer.six. pyHanko's PDF reader is its own implementation. The claim may be outdated -- verify with `pip show pyhanko | grep Requires` after installation. If false, pdfminer.six must be added as an explicit dependency.

---

## Unresolved Questions

1. **What pyHanko version is targeted?** API patterns differ across versions. The plan must pin a version range.
2. **Does the tool need to handle PDF/A compliance?** Adding signature fields via incremental write generally preserves PDF/A, but this should be tested with a PDF/A validator.
3. **What happens when "Employee Name" appears in a watermark or background layer?** pdfminer.six extracts text from all content streams regardless of layer/optional content group. The tool may place signature fields on decorative text.
4. **Is there a maximum page count?** pdfminer.six's `extract_pages()` processes all pages. A 500-page document with "Employee Name" on page 1 still takes full-document parse time.
5. **Should the CLI support stdin/stdout piping?** Important for CI/CD pipeline integration.

---

## Summary Table

| ID | Severity | Title | Effort to Fix |
|----|----------|-------|---------------|
| C1 | CRITICAL | Rotated pages break coordinate assumption | Medium |
| C2 | CRITICAL | Unrestricted file upload | Low |
| C3 | CRITICAL | Temp file cleanup race condition | Low |
| C4 | CRITICAL | Existing AcroForm/signature corruption | Medium |
| C5 | CRITICAL | Duplicate field names on reprocessing | Low |
| I1 | IMPORTANT | LTTextLine outside LTTextBox hierarchy | Low |
| I2 | IMPORTANT | "Employee Name" split across elements | Medium |
| I3 | IMPORTANT | Variable page sizes cause wrong coords | Medium |
| I4 | IMPORTANT | No handling of parse failures | Low |
| I5 | IMPORTANT | Seekable stream requirement | Low |
| I6 | IMPORTANT | Padding pushes box off-page | Low |
| I7 | IMPORTANT | CLI path arguments not validated | Low |
| M1 | MODERATE | LAParams defaults untested | Low |
| M2 | MODERATE | Async endpoint blocks event loop | Low |
| M3 | MODERATE | python-multipart not pinned | Low |
| M4 | MODERATE | No logging | Low |
| M5 | MODERATE | Test strategy gaps | Medium |
| M6 | MODERATE | pyHanko version not pinned | Low |
| M7 | MODERATE | No CORS configuration | Low |
| M8 | MODERATE | Single-threaded bottleneck | Low |

---

## Sources

- [pdfminer.six #454 -- Rotated character bounding boxes](https://github.com/pdfminer/pdfminer.six/issues/454)
- [pdfminer.six #702 -- Incorrect coordinates with variable page sizes](https://github.com/pdfminer/pdfminer.six/issues/702)
- [pdfminer.six #763 -- LTTextLine outside LTTextBox](https://github.com/pdfminer/pdfminer.six/issues/763)
- [pdfminer.six #900 -- CropBox inaccessible from LTPage](https://github.com/pdfminer/pdfminer.six/issues/900)
- [pdfminer.six #519 -- LTWord not implemented](https://github.com/pdfminer/pdfminer.six/issues/519)
- [pyHanko #150 -- Signature on rotated pages](https://github.com/MatthiasValvekens/pyHanko/discussions/150)
- [pyHanko signature fields docs](https://docs.pyhanko.eu/en/latest/lib-guide/sig-fields.html)
- [CVE-2024-24762 -- FastAPI/python-multipart ReDoS](https://security.snyk.io/vuln/SNYK-PYTHON-FASTAPI-6228055)
- [CVE-2026-28356 -- multipart ReDoS](https://dailycve.com/multipart-python-library-redos-cve-2026-28356-high/)
- [FastAPI secure file uploads](https://noone-m.github.io/2025-12-10-fastapi-file-upload/)
