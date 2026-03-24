# Brainstorm: eSign Web UI — Visual Field Placement + Native PDF Signing

**Date:** 2026-03-24
**Status:** Complete

---

## Problem Statement

The auto-detection approach (searching for "Employee Name" text) is fragile — real PDFs use brackets, varying case, different labels. Need a visual UI where the preparer manually places signature and date fields on the PDF, then downloads a prepared PDF that any signer can fill in using their native PDF viewer.

## Requirements

1. Web app (no auth, no accounts, no persistence, stateless)
2. Upload PDF → render in browser → drag-to-place fields
3. Field types: Name/Signature (text), Date (auto-fill)
4. Download prepared PDF with native AcroForm form fields
5. Signer opens prepared PDF in any PDF viewer (Adobe Reader, Preview, etc.)
6. Typed name is primary signing method
7. Date auto-fills when possible (Adobe Reader JS), manual fallback

## Evaluated Approaches

### A: pyHanko Signature Fields (Current)
- Adds cryptographic signature fields requiring certs
- Overkill for "type your name" use case
- Signer needs certificate setup in Adobe
- **Verdict: Wrong tool for the job**

### B: pypdf AcroForm Text Fields (Recommended)
- Adds standard form text fields to PDF
- Works in all PDF viewers
- Can set font appearance, default values, JavaScript actions
- Lightweight, pure Python, well-maintained
- **Verdict: Right fit — simple text fields for name + date**

### C: reportlab Overlay
- Generate form fields via reportlab, merge with original PDF
- More complex, two-step process
- **Verdict: Unnecessary complexity over pypdf**

## Recommended Solution

### Frontend (No build step)
- `static/index.html` — single page app
- **PDF.js** (Mozilla) — renders PDF pages to canvas in browser
- Vanilla JS — drag-to-place rectangles for field placement
- Field types: "Name" (blue box) and "Date" (green box)
- Multi-page support: navigate pages, place fields on any page
- Sends field definitions (page, x, y, width, height, type) + PDF to backend

### Backend (FastAPI)
- `POST /api/prepare` — receives PDF + field definitions JSON
- Uses **pypdf** to add AcroForm text fields at specified coordinates
- Sets font appearance for name fields (signature-like if possible)
- Adds JavaScript action on date fields: `event.value = util.printd("mm/dd/yyyy", new Date())`
- Returns prepared PDF for download

### Coordinate Mapping
- PDF.js renders at a certain scale → need to map screen coordinates back to PDF points
- Frontend tracks: canvas scale factor, PDF page dimensions
- Formula: `pdf_x = screen_x / scale`, `pdf_y = page_height - (screen_y / scale)` (flip Y axis)

### File Structure
```
src/esign/
├── api.py          # Update: add /api/prepare endpoint
├── prepare.py      # NEW: pypdf AcroForm field placement
├── cli.py          # Keep existing
├── extractor.py    # Keep existing
├── signer.py       # Keep existing
static/
├── index.html      # Single-page app
├── app.js          # PDF rendering + field placement UI
├── style.css       # UI styling
```

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Date JS only works in Adobe Reader | Fallback: empty text field, signer fills manually |
| PDF.js rendering differs from native viewer | Coordinates are in PDF points, not pixels — conversion is reliable |
| Large PDFs slow to render | PDF.js handles this well; lazy page loading |
| Font appearance in form fields | PDF viewers use their own fonts; we set a preference but can't force signature fonts |

## What We're NOT Building
- Email client
- User accounts / authentication
- Document storage / persistence
- Cryptographic digital signatures
- Web-based signing experience (signing happens in native PDF viewer)

## Next Steps
1. Add `pypdf` dependency
2. Create `prepare.py` module (AcroForm field creation)
3. Build frontend (HTML + PDF.js + drag UI)
4. Wire up `/api/prepare` endpoint
5. Test with real offer letter PDF
