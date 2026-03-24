# Code Review: eSign Employee Name Implementation

## Verdict

**PASS with issues.** The implementation is well-structured with clean separation of concerns, solid test coverage (28/28 passing), and good error handling. Three issues require attention: a pattern-building bug for multi-space search text, blocking sync calls in the async API handler, and minimum-size enforcement being silently violated by page-edge clamping.

---

## Scope

- **Files reviewed:** 9 source + test files (extractor, signer, cli, api, pyproject.toml, 5 test files)
- **LOC:** ~350 source, ~300 test
- **Tests:** 28/28 passing
- **Compile:** All 4 source modules clean

---

## Critical Issues

None.

---

## Important Issues

### [IMPORTANT] extractor.py:56 -- Pattern building fails for multi-space custom search text

The pattern-building logic for custom `search_text` values produces incorrect regex when the input contains consecutive spaces.

```python
escaped = re.escape(search_text.strip())           # "Employee\ \ Name"
pattern = re.compile(r"\s+".join(escaped.split(r"\ ")), re.IGNORECASE)
```

When `search_text = "Employee  Name"` (double space), `re.escape` produces `"Employee\ \ Name"`. Splitting on `r"\ "` yields `["Employee", "", "Name"]`, and joining with `\s+` produces `"Employee\s+\s+Name"` -- which requires two or more whitespace groups and **fails to match** `"Employee Name"` (single space).

**Impact:** Any user-provided search text with multiple consecutive spaces silently finds zero matches.

**Fix:** Replace the split/join approach with a single regex substitution:
```python
pattern = re.compile(re.escape(search_text.strip()).replace(r"\ ", r"\s+"), re.IGNORECASE)
```
Or, cleaner: split the original text on whitespace first, escape each word, then join:
```python
words = search_text.strip().split()
pattern = re.compile(r"\s+".join(re.escape(w) for w in words), re.IGNORECASE)
```

---

### [IMPORTANT] api.py:26 -- Blocking sync calls in async handler

`prepare_pdf` is `async def` but calls `find_text_locations()` and `add_signature_fields()` synchronously. Both perform CPU-bound PDF parsing (pdfminer layout analysis, pyHanko incremental write). On a real PDF, each parse takes ~25ms; together ~50ms. Under concurrent load, these block the event loop and starve other requests.

**Impact:** API throughput degrades under concurrency. A large PDF could block for hundreds of milliseconds.

**Fix:** Wrap CPU-bound calls in `run_in_executor`:
```python
import asyncio

loop = asyncio.get_running_loop()
text_locations = await loop.run_in_executor(None, find_text_locations, content, search_text)
```
Or use Starlette's `run_in_threadpool`:
```python
from starlette.concurrency import run_in_threadpool

text_locations = await run_in_threadpool(find_text_locations, content, search_text)
```

---

### [IMPORTANT] api.py:26-28 -- File fully read into memory before size check

`await file.read()` reads the entire upload into memory, then checks `len(content) > MAX_UPLOAD_SIZE`. A malicious client can send a multi-GB body before the check triggers. FastAPI/Starlette has no built-in request body size limit by default.

**Impact:** Memory exhaustion DoS with oversized uploads.

**Fix:** Read in chunks and abort early:
```python
chunks = []
size = 0
async for chunk in file:
    size += len(chunk)
    if size > MAX_UPLOAD_SIZE:
        return JSONResponse(status_code=413, content={"detail": "File too large"})
    chunks.append(chunk)
content = b"".join(chunks)
```
Or configure a reverse proxy (nginx) with `client_max_body_size` in production.

---

## Moderate Issues

### [MODERATE] signer.py:68-78 -- min_width/min_height silently violated after clamping

`_compute_box` enforces minimum dimensions (lines 62-71) then clamps to page bounds (lines 74-78). When the expanded box exceeds the page edge, clamping shrinks it back below the minimum. Verified: a box at x=600 with `min_width=200` on a 612pt page results in effective width 109.5pt -- minimum not met.

**Impact:** Signature fields near page edges may be undersized with no warning. The caller has no way to know the minimum was not achieved.

**Fix options:**
1. Shift the box inward before clamping (preferred): if expanding causes overflow, translate instead of just clamping.
2. Log a warning when post-clamp dimensions are below the requested minimum.
3. Accept current behavior as intentional (page boundary is a hard constraint) but document it.

---

### [MODERATE] cli.py:60 + api.py:45 -- _count_pages duplicates full PDF parsing

Both `cli.py` and `api.py` define `_count_pages()` which runs `extract_pages()` -- the same full layout analysis already performed by `find_text_locations()`. This doubles parsing time (~25ms extra per call measured on the sample PDF).

**Impact:** Unnecessary CPU and latency. Also, code duplication (DRY violation).

**Fix:** Have `find_text_locations()` return the page count alongside results:
```python
@dataclass
class ExtractionResult:
    locations: list[TextLocation]
    pages_scanned: int
```
Or track page count via `enumerate()` already in the loop:
```python
page_count = 0
for page_index, page_layout in enumerate(pages):
    page_count = page_index + 1
    ...
return results, page_count
```

---

### [MODERATE] signer.py:29 -- Accessing internal pyHanko reader via `writer.prev`

`_get_existing_field_names` accesses `writer.prev` (the underlying `PdfFileReader`) which is an implementation detail of `IncrementalPdfFileWriter`. This is fragile across pyHanko version upgrades.

**Impact:** Could break silently on pyHanko updates.

**Mitigation:** Pin pyHanko more tightly or add a test that explicitly validates this accessor works. Consider using pyHanko's public API if one exists for field enumeration.

---

### [MODERATE] pyproject.toml:11-17 -- Dependencies use >= without upper bounds

All dependencies use `>=` with no upper bounds:
```
"pyhanko>=0.25",
"pdfminer.six>=20231228",
"fastapi>=0.115",
```

**Impact:** A major version bump in any dependency could introduce breaking changes in CI or production.

**Fix:** Add upper bounds or use `~=` for compatible releases:
```
"pyhanko>=0.25,<1.0",
"pdfminer.six>=20231228,<20260000",
```
Or use a lockfile (`pip-compile`, `uv lock`).

---

## Low Priority

### [CLEAN] extractor.py:58-59 -- Hardcoded default pattern bypass is correct but fragile

Lines 58-59 use `if search_text == "Employee Name"` to bypass the dynamically-built pattern in favor of `_SEARCH_PATTERN`. This works but means the default path and custom path use different regex engines. Consider always using the dynamic path (after fixing the multi-space bug above) and removing the special case.

### [CLEAN] cli.py:27-38 -- Good path traversal defense

The CLI validates input existence and uses `Path` objects throughout. The `--output` flag defaults to the same directory as the input. No user-controlled path components are interpolated into sensitive operations. No path traversal risk.

### [CLEAN] api.py:37-40 -- Error messages do not leak internal details

Exception messages are mapped to generic user-facing strings ("Invalid or corrupted PDF", "Internal processing error"). No stack traces, file paths, or library names exposed.

---

## Edge Cases Found by Scouting

| Edge Case | Status | Detail |
|-----------|--------|--------|
| Multi-space search text | **BUG** | Pattern fails to match single-space text (extractor.py:56) |
| min_width/min_height near page edge | **SILENT VIOLATION** | Clamping undoes minimum enforcement (signer.py:74-78) |
| Zero-page PDF | OK | Returns empty list, no crash |
| Encrypted PDF | OK | Raises ValueError("PDF is encrypted") |
| Empty bytes | OK | Raises ValueError("Invalid PDF") |
| Malformed (non-PDF) bytes | OK | Caught by magic bytes check and PDFSyntaxError |
| Single-word search text | OK | Pattern builds correctly |
| Special regex chars in search text | OK | `re.escape` neutralizes them |
| ReDoS via search_text | OK | Linear-time pattern, no catastrophic backtracking |
| Content-Disposition injection | OK | Filename is hardcoded |
| Double processing (reprocess) | OK | Duplicate fields detected and skipped |

---

## Positive Observations

- **Clean architecture**: extractor -> signer -> interface layers are well-separated. No cross-layer leakage.
- **Comprehensive test coverage**: 28 tests cover happy paths, error paths, edge cases, clamping, naming, and reprocessing.
- **Correct coordinate system**: pdfminer.six returns native PDF coords (bottom-left origin). pyHanko's `SigFieldSpec.box` also uses PDF coords. No coordinate transformation needed -- and correctly none is applied.
- **Incremental writes**: Using `IncrementalPdfFileWriter` preserves original PDF structure and signatures.
- **Defensive validation**: Magic bytes check in both CLI and API. Encrypted PDF detection. Empty input handling.
- **Dataclass usage**: `TextLocation`, `SignatureFieldResult`, `PrepareResult` provide clean typed interfaces.

---

## Recommended Actions (Priority Order)

1. **Fix multi-space pattern bug** in extractor.py:56 (Important, correctness)
2. **Add `run_in_threadpool` wrapper** for sync calls in api.py (Important, performance under load)
3. **Add chunked upload reading** or reverse proxy size limit (Important, DoS prevention)
4. **Refactor `_count_pages` out** -- return page count from `find_text_locations` (Moderate, DRY + perf)
5. **Decide on min_size vs. clamping behavior** -- document or fix (Moderate, correctness)
6. **Add upper bounds to dependencies** in pyproject.toml (Moderate, stability)

---

## Metrics

| Metric | Value |
|--------|-------|
| Source files | 4 (+1 __init__) |
| Source LOC | ~350 |
| Test files | 5 (incl. conftest, fixture generator) |
| Test LOC | ~300 |
| Tests passing | 28/28 |
| Type hints | Present on all public functions |
| Docstrings | Present on all public functions |
| Linting issues | 0 (compile clean) |
| Critical findings | 0 |
| Important findings | 3 |
| Moderate findings | 3 |

---

## Unresolved Questions

1. Is the min_width/min_height clamping behavior intentional? If fields near page edges should never be undersized, the box should shift inward rather than clamp. If the page boundary is the hard constraint, the current behavior is correct but should be documented.
2. Will this API run behind a reverse proxy in production? If yes, the chunked-read fix for DoS is lower priority since nginx/traefik can enforce body size limits.
3. Should `find_text_locations` support returning page count natively, or is the `_count_pages` duplication acceptable for the current scope?
