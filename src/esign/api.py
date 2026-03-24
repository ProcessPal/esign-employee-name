"""FastAPI interface for the eSign Employee Name service."""

from __future__ import annotations

import asyncio
import json
from functools import partial
from pathlib import Path

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from esign.extractor import find_text_locations
from esign.prepare import add_form_fields, stamp_fields_onto_pdf
from esign.signer import add_signature_fields

app = FastAPI(title="eSign Employee Name API", version="0.1.0")

MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB
READ_CHUNK_SIZE = 64 * 1024  # 64 KB

# Serve static files for the web UI
STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    """Serve the web UI."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return Response(content=index_path.read_text(), media_type="text/html")
    return JSONResponse(status_code=404, content={"detail": "UI not found"})


@app.get("/health")
def health():
    return {"status": "ok"}


# --- Web UI endpoint: visual field placement ---


@app.post("/api/prepare")
async def api_prepare_fields(
    file: UploadFile = File(...),
    fields: str = Form(...),
):
    """Accept a PDF + field positions from the web UI, return PDF with AcroForm fields."""
    chunks: list[bytes] = []
    total_size = 0
    while True:
        chunk = await file.read(READ_CHUNK_SIZE)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > MAX_UPLOAD_SIZE:
            return JSONResponse(status_code=413, content={"detail": "File too large"})
        chunks.append(chunk)

    content = b"".join(chunks)

    if len(content) < 5 or content[:5] != b"%PDF-":
        return JSONResponse(status_code=400, content={"detail": "Invalid or corrupted PDF"})

    try:
        field_defs = json.loads(fields)
    except (json.JSONDecodeError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid field definitions"})

    if not field_defs:
        return JSONResponse(status_code=400, content={"detail": "No fields specified"})

    loop = asyncio.get_event_loop()

    try:
        result_bytes = await loop.run_in_executor(
            None, partial(add_form_fields, content, field_defs)
        )
    except Exception as exc:
        return JSONResponse(status_code=500, content={"detail": f"Processing error: {exc}"})

    return Response(
        content=result_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="prepared_document.pdf"',
            "X-Fields-Added": str(len(field_defs)),
        },
    )


# --- Web UI endpoint: sign and flatten ---


@app.post("/api/sign")
async def api_sign_pdf(
    request: Request,
    file: UploadFile = File(...),
    fields: str = Form(...),
):
    """Stamp field values directly onto the PDF. Returns a flat, non-editable signed PDF."""
    chunks: list[bytes] = []
    total_size = 0
    while True:
        chunk = await file.read(READ_CHUNK_SIZE)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > MAX_UPLOAD_SIZE:
            return JSONResponse(status_code=413, content={"detail": "File too large"})
        chunks.append(chunk)

    content = b"".join(chunks)

    if len(content) < 5 or content[:5] != b"%PDF-":
        return JSONResponse(status_code=400, content={"detail": "Invalid or corrupted PDF"})

    try:
        field_defs = json.loads(fields)
    except (json.JSONDecodeError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid field definitions"})

    if not field_defs:
        return JSONResponse(status_code=400, content={"detail": "No fields specified"})

    # Verify all name fields have values
    empty_names = [f for f in field_defs if f.get("type") == "name" and not f.get("value", "").strip()]
    if empty_names:
        return JSONResponse(status_code=422, content={"detail": "All signature fields must have values"})

    # Collect verification metadata
    import hashlib
    from datetime import datetime, timezone

    client_ip = request.client.host if request.client else "unknown"
    # Check for proxy headers
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()

    verification = {
        "ip": client_ip,
        "user_agent": request.headers.get("user-agent", "unknown"),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "doc_hash": hashlib.sha256(content).hexdigest(),
    }

    loop = asyncio.get_event_loop()

    try:
        result_bytes = await loop.run_in_executor(
            None, partial(stamp_fields_onto_pdf, content, field_defs, verification)
        )
    except Exception as exc:
        return JSONResponse(status_code=500, content={"detail": f"Processing error: {exc}"})

    return Response(
        content=result_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="signed_document.pdf"',
            "X-Fields-Signed": str(len(field_defs)),
        },
    )


# --- Original auto-detect endpoint ---


@app.post("/prepare")
async def prepare_pdf(
    file: UploadFile = File(...),
    search_text: str = Query("Employee Name", description="Text to search for"),
):
    """Auto-detect 'Employee Name' and add signature fields."""
    chunks: list[bytes] = []
    total_size = 0
    while True:
        chunk = await file.read(READ_CHUNK_SIZE)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > MAX_UPLOAD_SIZE:
            return JSONResponse(status_code=413, content={"detail": "File too large"})
        chunks.append(chunk)

    content = b"".join(chunks)

    if len(content) < 5 or content[:5] != b"%PDF-":
        return JSONResponse(status_code=400, content={"detail": "Invalid or corrupted PDF"})

    loop = asyncio.get_event_loop()

    try:
        extraction = await loop.run_in_executor(
            None, partial(find_text_locations, content, search_text)
        )
    except ValueError as exc:
        msg = str(exc)
        if "encrypted" in msg:
            return JSONResponse(status_code=400, content={"detail": "PDF is encrypted"})
        return JSONResponse(status_code=400, content={"detail": "Invalid or corrupted PDF"})
    except Exception:
        return JSONResponse(status_code=500, content={"detail": "Internal processing error"})

    if not extraction.locations:
        return JSONResponse(
            status_code=422,
            content={
                "detail": "Text not found",
                "search_text": search_text,
                "pages_scanned": extraction.pages_scanned,
            },
        )

    signer_locations = [
        (loc.page_index, loc.box, loc.page_width, loc.page_height)
        for loc in extraction.locations
    ]

    try:
        result = await loop.run_in_executor(
            None, partial(add_signature_fields, content, signer_locations)
        )
    except ValueError as exc:
        msg = str(exc)
        if "encrypted" in msg:
            return JSONResponse(status_code=400, content={"detail": "PDF is encrypted"})
        return JSONResponse(status_code=400, content={"detail": "Invalid or corrupted PDF"})
    except Exception:
        return JSONResponse(status_code=500, content={"detail": "Internal processing error"})

    return Response(
        content=result.pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="prepared.pdf"',
            "X-Fields-Added": str(len(result.fields_added)),
        },
    )
