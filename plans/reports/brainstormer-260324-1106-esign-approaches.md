# Brainstorm: E-Sign Employee Name -- Implementation Approaches

**Date:** 2026-03-24  
**Status:** Complete  
**Project:** /Users/matt/CascadeProjects/esign-employee-name

---

## Problem Statement

Build an application that:
1. Accepts a PDF document (web upload or CLI)
2. Locates the text "Employee Name" and determines its exact page coordinates
3. Uses pyHanko to place a digital signature field at that location
4. Returns the modified PDF with an unsigned signature field ready for e-signing

### Key Constraints
- pyHanko is the required signing library
- Signature location must be auto-detected from "Employee Name" text
- Greenfield project -- no existing code

---

## Critical Technical Finding: Coordinate System Mismatch

**This is the single biggest risk in this project.** The three PDF extraction libraries and pyHanko each use different coordinate systems:

| Library | Origin | Y-axis | Format |
|---------|--------|--------|--------|
| **pyHanko** (PDF standard) | Bottom-left | Up | `(x1, y1, x2, y2)` Cartesian |
| **PyMuPDF/fitz** | Top-left | Down | `Rect(x0, y0, x1, y1)` |
| **pdfplumber** | Top-left | Down | `(x0, top, x1, bottom)` |
| **pdfminer.six** | Bottom-left | Up | `(x0, y0, x1, y1)` Cartesian |

**Implication:** PyMuPDF and pdfplumber coordinates must be converted before passing to pyHanko. pdfminer.six natively matches pyHanko's coordinate system.

Conversion formula (PyMuPDF/pdfplumber to pyHanko):
```
pyhanko_y = page_height - extraction_y
```

---

## Approach A: PyMuPDF + FastAPI (Speed-Optimized)

### Stack
- **Text extraction:** PyMuPDF (fitz) -- `page.search_for("Employee Name")`
- **Signature field:** pyHanko `append_signature_field` + `SigFieldSpec`
- **Interface:** FastAPI with file upload endpoint
- **Certificate:** Optional (field-only mode by default)

### Architecture
```
[Upload PDF] -> FastAPI endpoint
  -> PyMuPDF: search_for("Employee Name") -> list[Rect]
  -> Convert coords: fitz top-left -> PDF bottom-left
  -> pyHanko: append_signature_field(SigFieldSpec(box=...))
  -> Return modified PDF via StreamingResponse
```

### Core Logic Sketch
```python
import fitz
from pyhanko.sign.fields import SigFieldSpec, append_signature_field
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

def locate_and_prepare(pdf_bytes: bytes, search_text: str = "Employee Name"):
    # 1. Find text coordinates with PyMuPDF
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    locations = []
    for page_num, page in enumerate(doc):
        rects = page.search_for(search_text)
        page_height = page.rect.height
        for rect in rects:
            # Convert from fitz (top-left origin) to PDF (bottom-left origin)
            box = (rect.x0, page_height - rect.y1, rect.x1, page_height - rect.y0)
            locations.append((page_num, box))
    doc.close()

    # 2. Add signature fields with pyHanko
    import io
    buf = io.BytesIO(pdf_bytes)
    w = IncrementalPdfFileWriter(buf)
    for i, (page_num, box) in enumerate(locations):
        spec = SigFieldSpec(
            sig_field_name=f"EmployeeSig_{i}",
            on_page=page_num,
            box=box
        )
        append_signature_field(w, spec)
    
    output = io.BytesIO()
    w.write(output)
    output.seek(0)
    return output, locations
```

### Pros
- **Fastest extraction:** PyMuPDF is ~60x faster than pdfminer.six (42ms vs 2500ms per doc)
- **Built-in search:** `page.search_for()` returns Rect objects directly -- no manual text assembly
- **Handles rotated pages:** PyMuPDF provides `transformation_matrix` for rotated page support
- **Mature async story:** FastAPI + PyMuPDF works well for concurrent requests
- **Rich PDF manipulation:** PyMuPDF can also highlight, annotate, render previews

### Cons
- **Coordinate conversion required:** Must flip Y-axis for pyHanko compatibility (bug-prone)
- **C dependency:** PyMuPDF bundles MuPDF (C library) -- larger install, potential build issues on some platforms
- **License:** PyMuPDF uses AGPL (or commercial) -- may be a concern for proprietary use
- **Two PDF opens:** Must open PDF twice (once in fitz, once in pyHanko's writer) since they use different internal representations

### Risk Assessment
- **Low:** Text detection reliability (PyMuPDF's search is robust)
- **Medium:** Coordinate conversion bugs, especially with rotated/cropped pages
- **Low:** Performance (fast enough for batch processing)
- **Medium:** AGPL license if distributing commercially

---

## Approach B: pdfplumber + CLI-First (Simplicity-Optimized)

### Stack
- **Text extraction:** pdfplumber -- `page.extract_words()` with manual text matching
- **Signature field:** pyHanko `append_signature_field` + `SigFieldSpec`
- **Interface:** CLI with Click/Typer, optional FastAPI wrapper later
- **Certificate:** Self-signed demo cert bundled, configurable via CLI flags

### Architecture
```
[CLI: python main.py input.pdf -o output.pdf]
  -> pdfplumber: extract_words() -> filter for "Employee" + "Name"
  -> Convert coords: pdfplumber top-left -> PDF bottom-left  
  -> pyHanko: append_signature_field(SigFieldSpec(box=...))
  -> Write output PDF
```

### Core Logic Sketch
```python
import pdfplumber
from pyhanko.sign.fields import SigFieldSpec, append_signature_field
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

def find_employee_name(pdf_path: str):
    locations = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            words = page.extract_words()
            page_height = float(page.height)
            # Find consecutive "Employee" + "Name" words
            for i, w in enumerate(words):
                if w["text"] == "Employee" and i + 1 < len(words):
                    next_w = words[i + 1]
                    if next_w["text"] == "Name":
                        # Merge bounding boxes
                        x0 = min(w["x0"], next_w["x0"])
                        x1 = max(w["x1"], next_w["x1"])
                        top = min(w["top"], next_w["top"])
                        bottom = max(w["bottom"], next_w["bottom"])
                        # Convert to PDF coordinates (bottom-left origin)
                        box = (x0, page_height - bottom, x1, page_height - top)
                        locations.append((page_num, box))
    return locations
```

### Pros
- **Pure Python:** No C dependencies -- installs cleanly everywhere via pip
- **Best debugging:** pdfplumber offers visual debugging (`page.to_image()` to inspect extraction)
- **Word-level data:** `extract_words()` gives individual word positions -- easier to match multi-word phrases
- **CLI-first is simpler:** No web framework overhead, easier to test and script
- **Liberal license:** MIT license on pdfplumber

### Cons
- **Slower extraction:** Built on pdfminer.six, roughly 60x slower than PyMuPDF
- **Manual text matching:** No built-in `search_for()` -- must implement word-joining logic for "Employee Name"
- **Coordinate conversion still needed:** pdfplumber uses top-left origin, must convert for pyHanko
- **Word splitting edge cases:** If "Employee Name" is rendered as a single text run (no space break), `extract_words()` may return it as one word; conversely, unusual spacing could split it differently
- **CLI-only initially:** Would need to add FastAPI later for web upload use case

### Risk Assessment
- **Medium:** Text matching reliability (word boundary detection varies by PDF)
- **Medium:** Coordinate conversion (same issue as Approach A)
- **Low:** Deployment/installation (pure Python)
- **High:** Performance if processing many PDFs (seconds per doc)

---

## Approach C: pdfminer.six + Hybrid CLI/API (Correctness-Optimized)

### Stack
- **Text extraction:** pdfminer.six directly -- `LAParams` + `LTTextBox`/`LTChar` layout analysis
- **Signature field:** pyHanko `append_signature_field` + `SigFieldSpec`
- **Interface:** Typer CLI + FastAPI in same package (shared core)
- **Certificate:** Configurable via YAML/env vars, self-signed generator included

### Architecture
```
[CLI or API] -> core.locate_signature_position(pdf)
  -> pdfminer.six: high-level layout analysis -> LTTextBox/LTTextLine
  -> Coordinates already in PDF standard (bottom-left) -- NO CONVERSION NEEDED
  -> pyHanko: append_signature_field(SigFieldSpec(box=...))
  -> Return/write modified PDF
```

### Core Logic Sketch
```python
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextBox, LTTextLine, LTChar, LAParams

def find_employee_name_pdfminer(pdf_path: str):
    locations = []
    laparams = LAParams(word_margin=0.2)  # Fine-tune word grouping
    for page_num, page_layout in enumerate(extract_pages(pdf_path, laparams=laparams)):
        for element in page_layout:
            if isinstance(element, LTTextBox):
                for line in element:
                    if isinstance(line, LTTextLine):
                        text = line.get_text().strip()
                        if "Employee Name" in text:
                            # Coordinates are already in PDF standard (bottom-left origin)
                            box = (line.x0, line.y0, line.x1, line.y1)
                            locations.append((page_num, box))
    return locations
```

### Hybrid Interface
```python
# cli.py (Typer)
@app.command()
def prepare(input_pdf: Path, output_pdf: Path, search_text: str = "Employee Name"):
    ...

# api.py (FastAPI)
@app.post("/prepare")
async def prepare_pdf(file: UploadFile):
    ...

# Both call the same core function
```

### Pros
- **No coordinate conversion:** pdfminer.six uses the same bottom-left Cartesian system as pyHanko -- eliminates the #1 source of bugs
- **Most accurate layout analysis:** pdfminer.six has the most sophisticated layout analysis engine (LAParams tuning)
- **Pure Python:** No C dependencies (same benefit as pdfplumber)
- **Hybrid interface:** CLI for scripting/CI, API for web upload -- both from day one
- **Character-level access:** Can drill down to `LTChar` for precise bounding boxes if needed
- **Shared dependency:** pdfminer.six is already a transitive dependency of pyHanko itself

### Cons
- **Slowest extraction:** Same performance as pdfplumber (they share the same engine)
- **More verbose API:** pdfminer.six has a lower-level API; more boilerplate than PyMuPDF's `search_for()`
- **No visual debugging:** Unlike pdfplumber, no built-in `to_image()` for inspection
- **Layout analysis sensitivity:** `LAParams` tuning may be needed per document type (word_margin, line_margin, etc.)
- **Two interfaces = more code:** Maintaining both CLI and API from the start

### Risk Assessment
- **Lowest:** Coordinate correctness (native match with pyHanko)
- **Low:** Text detection (pdfminer.six layout analysis is battle-tested)
- **Medium:** LAParams tuning for diverse PDFs
- **Low:** Deployment (pure Python, shared transitive dep)

---

## Comparative Analysis

| Criterion | A: PyMuPDF+FastAPI | B: pdfplumber+CLI | C: pdfminer.six+Hybrid |
|-----------|-------------------|-------------------|------------------------|
| **Extraction speed** | Excellent (42ms) | Poor (2500ms) | Poor (2500ms) |
| **Coordinate safety** | Needs conversion | Needs conversion | Native match |
| **Install simplicity** | C dep (bundled) | Pure Python | Pure Python |
| **Search API** | `search_for()` built-in | Manual word joining | Manual layout traversal |
| **License** | AGPL/Commercial | MIT | MIT |
| **Debug tooling** | Good (rendering) | Best (visual debug) | Basic |
| **Shared dep with pyHanko** | No | No (but shares pdfminer) | Yes (transitive dep) |
| **Interface flexibility** | API only initially | CLI only initially | Both from start |
| **Rotated page handling** | Built-in matrices | Manual | Manual |
| **Lines of code (est.)** | ~200 | ~150 | ~250 |

---

## Recommendation: Approach C (pdfminer.six + Hybrid)

### Rationale

1. **Coordinate correctness is paramount.** The entire value of this tool is placing a signature field at the right location. pdfminer.six's native PDF coordinate system eliminates the most dangerous class of bugs. A coordinate conversion error means the signature field appears in the wrong place -- and on some PDFs, it could be invisible (off-page).

2. **Shared dependency.** pyHanko already depends on pyHanko-certvalidator and uses PDF internals compatible with pdfminer.six. Using pdfminer.six means one fewer dependency to install and no conflicting PDF interpretations.

3. **Performance is acceptable.** For a tool processing individual documents (not batch millions), 2-3 seconds per PDF is fine. If batch performance becomes critical later, PyMuPDF can be swapped in as the extractor without changing the pyHanko integration layer.

4. **Hybrid interface serves both use cases** from the start without significant extra complexity -- the core logic is shared, and the CLI/API layers are thin wrappers.

5. **MIT license** avoids any AGPL concerns.

### Suggested Project Structure

```
esign-employee-name/
├── pyproject.toml
├── README.md
├── src/
│   └── esign/
│       ├── __init__.py
│       ├── core.py          # locate_text(), prepare_signature_field()
│       ├── extractor.py     # pdfminer.six text location extraction
│       ├── signer.py        # pyHanko SigFieldSpec creation
│       ├── cli.py           # Typer CLI
│       └── api.py           # FastAPI endpoints
├── tests/
│   ├── test_extractor.py
│   ├── test_signer.py
│   ├── test_cli.py
│   ├── test_api.py
│   └── fixtures/
│       └── sample.pdf       # Test PDF with "Employee Name" text
├── certs/
│   └── README.md            # Instructions for cert generation
└── docs/
    └── system-architecture.md
```

### Key Implementation Decisions

1. **Field-only mode (no signing):** Default behavior adds an empty signature field. Actual signing with a certificate is a separate optional step. This matches the requirement "ready for e-signing."

2. **Multiple occurrences:** When "Employee Name" appears multiple times, create a separate named field for each (`EmployeeSig_0`, `EmployeeSig_1`, etc.). Return the count and locations in the response so the caller knows what was found.

3. **Not-found handling:** Return a clear error (HTTP 422 / CLI exit code 1) with a message listing what was searched for and which pages were scanned. Optionally dump extracted text for debugging.

4. **Signature box sizing:** The box should be slightly larger than the text bounding box (add padding of ~5-10 points on each side) to create a visually appropriate signature area.

5. **Extractor abstraction:** Define a simple `TextLocator` protocol/ABC so the extraction library can be swapped later (e.g., to PyMuPDF for performance) without touching the pyHanko integration code.

---

## Unresolved Questions

1. **Exact search text:** Is the search always literally "Employee Name", or should it be configurable (e.g., "Signature", "Sign Here", regex patterns)?

2. **Signature field size:** Should the signature box match the text bounding box exactly, or should it be a fixed size (e.g., 200x50 points) centered on the text location?

3. **Multiple occurrences policy:** Should all occurrences get signature fields, or only the first? Should the user be prompted to choose?

4. **Actual signing requirement:** Is the scope limited to *preparing* the field (adding an empty signature widget), or should the tool also *sign* with a certificate? The current requirement says "ready for e-signing" which implies field-only.

5. **PDF/A compliance:** Do the input PDFs need to maintain PDF/A compliance after modification? pyHanko supports PAdES signatures if needed.

6. **Deployment target:** Will this run as a persistent web service, a serverless function, a CI/CD pipeline step, or a desktop tool? This affects the interface priority (API vs CLI).

7. **Scanned PDFs:** Should the tool handle scanned/image-based PDFs where "Employee Name" is not extractable text? That would require OCR (e.g., Tesseract) -- a significant scope expansion.

---

## Sources

- [pyHanko Signature Fields Documentation](https://docs.pyhanko.eu/en/latest/lib-guide/sig-fields.html)
- [pyHanko Signing Functionality](https://docs.pyhanko.eu/en/latest/lib-guide/signing.html)
- [pyHanko CLI Signing Guide](https://docs.pyhanko.eu/en/latest/cli-guide/signing.html)
- [pyHanko GitHub Repository](https://github.com/MatthiasValvekens/pyHanko)
- [pyHanko v0.27.0 Signature Fields](https://docs.pyhanko.eu/en/v0.27.0/lib-guide/sig-fields.html)
- [pdfplumber GitHub Repository](https://github.com/jsvine/pdfplumber)
- [PyMuPDF Coordinate Systems Discussion](https://github.com/pymupdf/PyMuPDF/discussions/1806)
- [PyMuPDF Text Recipes](https://pymupdf.readthedocs.io/en/latest/recipes-text.html)
- [Comparing PDF Parsing Frameworks](https://www.ai-bites.net/comparing-6-frameworks-for-rule-based-pdf-parsing/)
- [PDF Extraction Libraries Performance Comparison](https://abhiyantimilsina.medium.com/a-comparative-analysis-of-pdf-extraction-libraries-choosing-the-fastest-solution-3b6bd8588498)
- [FastAPI Custom Responses](https://fastapi.tiangolo.com/advanced/custom-response/)
