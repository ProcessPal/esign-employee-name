"""Stamp text directly onto PDF pages — no overlays, no form fields, flat output."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
    create_string_object,
)


def _escape_pdf_string(text: str) -> str:
    """Escape special characters for a PDF text string."""
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _ensure_font_on_page(page: dict, writer: PdfWriter) -> str:
    """Ensure Helvetica-Bold is available on the page. Returns the font key."""
    font_key = "ESigF1"

    resources = page.get("/Resources")
    if resources is None:
        resources = DictionaryObject()
        page[NameObject("/Resources")] = resources
    else:
        resources = resources.get_object() if hasattr(resources, "get_object") else resources

    fonts = resources.get("/Font")
    if fonts is None:
        fonts = DictionaryObject()
        resources[NameObject("/Font")] = fonts
    else:
        fonts = fonts.get_object() if hasattr(fonts, "get_object") else fonts

    if NameObject(f"/{font_key}") not in fonts:
        font_obj = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica-Bold"),
        })
        font_ref = writer._add_object(font_obj)
        fonts[NameObject(f"/{font_key}")] = font_ref

    return font_key


def _append_content_stream(page: dict, writer: PdfWriter, stream_data: str):
    """Append a content stream to a page without replacing existing content."""
    new_stream = DecodedStreamObject()
    new_stream.set_data(stream_data.encode("latin-1"))
    new_ref = writer._add_object(new_stream)

    existing = page.get("/Contents")
    if existing is None:
        page[NameObject("/Contents")] = new_ref
    elif isinstance(existing, ArrayObject):
        existing.append(new_ref)
    else:
        page[NameObject("/Contents")] = ArrayObject([existing, new_ref])


def stamp_fields_onto_pdf(
    pdf_bytes: bytes,
    fields: list[dict],
    verification: dict | None = None,
) -> bytes:
    """Stamp text values directly onto PDF pages by injecting drawing commands.

    No overlays, no merging, no form fields. Text is permanently part of the page.

    Args:
        pdf_bytes: Original PDF bytes.
        fields: List of field definitions with:
            - page: int (0-based)
            - x_pct, y_pct, w_pct, h_pct: float (percentage coords)
            - value: str (text to stamp)
            - type: str ("name" or "date")
        verification: Optional dict with:
            - ip: str (signer's IP address)
            - user_agent: str (browser/device info)
            - timestamp: str (ISO 8601 signing time)
            - doc_hash: str (SHA-256 of original PDF)
    """
    import hashlib

    reader = PdfReader(BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)

    # Compute document hash if not provided
    doc_hash = ""
    if verification:
        doc_hash = verification.get("doc_hash", "")
    if not doc_hash:
        doc_hash = hashlib.sha256(pdf_bytes).hexdigest()

    # Group fields by page
    fields_by_page: dict[int, list[dict]] = {}
    for f in fields:
        page_idx = f.get("page", 0)
        fields_by_page.setdefault(page_idx, []).append(f)

    for page_idx, page_fields in fields_by_page.items():
        if page_idx >= len(writer.pages):
            continue

        page = writer.pages[page_idx]
        mb = reader.pages[page_idx].mediabox
        page_width = float(mb.width)
        page_height = float(mb.height)
        origin_x = float(mb.left)
        origin_y = float(mb.bottom)

        font_key = _ensure_font_on_page(page, writer)

        # Build drawing commands for all fields on this page
        commands = ["q"]  # Save graphics state

        for f in page_fields:
            value = f.get("value", "").strip()
            if not value:
                continue

            # Convert percentage to PDF coordinates (bottom-left origin)
            x = origin_x + f["x_pct"] * page_width
            h = f["h_pct"] * page_height
            # y_pct is from top, PDF y is from bottom
            # Position text baseline slightly above the bottom of the field box
            y_top = origin_y + page_height - f["y_pct"] * page_height
            y_baseline = y_top - h * 0.75  # baseline at ~75% down the field box

            font_size = min(h * 0.7, 14)
            escaped = _escape_pdf_string(value)

            commands.append("BT")
            commands.append(f"/{font_key} {font_size:.1f} Tf")
            commands.append(f"{x:.2f} {y_baseline:.2f} Td")
            commands.append(f"({escaped}) Tj")
            commands.append("ET")

        commands.append("Q")  # Restore graphics state

        _append_content_stream(page, writer, "\n".join(commands))

    # --- Verification footer on the last page that has signature fields ---
    if verification and fields:
        signed_pages = sorted(set(f.get("page", 0) for f in fields))
        last_signed_page = signed_pages[-1]
        if last_signed_page < len(writer.pages):
            vpage = writer.pages[last_signed_page]
            vmb = reader.pages[last_signed_page].mediabox
            vpw = float(vmb.width)
            vph = float(vmb.height)
            vox = float(vmb.left)
            voy = float(vmb.bottom)

            vfont_key = _ensure_font_on_page(vpage, writer)

            # Also add a smaller regular font for the verification block
            _ensure_verification_font(vpage, writer)

            ip = _escape_pdf_string(verification.get("ip", "unknown"))
            ua = verification.get("user_agent", "unknown")
            # Truncate user-agent to keep it readable
            if len(ua) > 80:
                ua = ua[:77] + "..."
            ua = _escape_pdf_string(ua)
            ts = _escape_pdf_string(verification.get("timestamp", "unknown"))
            dh = _escape_pdf_string(doc_hash[:16] + "..." + doc_hash[-16:])

            # Signer names
            signers = [f.get("value", "") for f in fields if f.get("type") == "name" and f.get("value")]
            signer_text = _escape_pdf_string(", ".join(signers)) if signers else "N/A"

            # Draw verification block at bottom of page
            fs = 6.5  # small font
            lh = 8.5  # line height
            margin = vox + 36  # 0.5 inch from left
            # Start from very bottom of page
            y_start = voy + 42  # ~0.58 inch from bottom

            # Light gray background box
            box_x = margin - 4
            box_y = y_start - 6
            box_w = vpw - 72 + 8
            box_h = lh * 5 + 10

            vcmds = ["q"]
            # Background
            vcmds.append(f"0.95 0.95 0.95 rg")
            vcmds.append(f"{box_x:.1f} {box_y:.1f} {box_w:.1f} {box_h:.1f} re f")
            # Border
            vcmds.append(f"0.8 0.8 0.8 RG 0.5 w")
            vcmds.append(f"{box_x:.1f} {box_y:.1f} {box_w:.1f} {box_h:.1f} re S")
            # Text
            vcmds.append(f"0 0 0 rg")  # black text

            lines = [
                f"eSign Verification  |  Signed by: {signer_text}",
                f"Timestamp: {ts}  |  IP: {ip}",
                f"Device: {ua}",
                f"Document Hash (SHA-256): {dh}",
            ]

            y_cur = y_start + lh * 3 + 2  # start from top of box
            for i, line in enumerate(lines):
                font = f"/ESigF2 {fs:.1f} Tf" if i > 0 else f"/ESigF2 {fs + 1:.1f} Tf"
                vcmds.append("BT")
                vcmds.append(font)
                vcmds.append(f"{margin:.1f} {y_cur:.1f} Td")
                vcmds.append(f"({line}) Tj")
                vcmds.append("ET")
                y_cur -= lh

            vcmds.append("Q")
            _append_content_stream(vpage, writer, "\n".join(vcmds))

    # Lock the PDF: encrypt with no user password (anyone can open/print)
    # but a random owner password (nobody can edit, fill forms, annotate, etc.)
    import secrets
    owner_pwd = secrets.token_hex(32)
    writer.encrypt(
        user_password="",
        owner_password=owner_pwd,
        permissions_flag=0b0000_0000_0000_0100,  # only allow printing
    )

    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _ensure_verification_font(page: dict, writer: PdfWriter) -> str:
    """Add a small regular Helvetica font for the verification block."""
    font_key = "ESigF2"
    resources = page.get("/Resources")
    if resources is None:
        resources = DictionaryObject()
        page[NameObject("/Resources")] = resources
    else:
        resources = resources.get_object() if hasattr(resources, "get_object") else resources

    fonts = resources.get("/Font")
    if fonts is None:
        fonts = DictionaryObject()
        resources[NameObject("/Font")] = fonts
    else:
        fonts = fonts.get_object() if hasattr(fonts, "get_object") else fonts

    if NameObject(f"/{font_key}") not in fonts:
        font_obj = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        font_ref = writer._add_object(font_obj)
        fonts[NameObject(f"/{font_key}")] = font_ref

    return font_key


def add_form_fields(
    pdf_bytes: bytes,
    fields: list[dict],
) -> bytes:
    """Add AcroForm text fields to a PDF (for the 'prepare & send' workflow).

    Uses percentage-based coordinates for reliability.
    """
    reader = PdfReader(BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)

    if "/AcroForm" not in writer._root_object:
        writer._root_object[NameObject("/AcroForm")] = DictionaryObject({
            NameObject("/Fields"): ArrayObject(),
            NameObject("/NeedAppearances"): BooleanObject(True),
        })

    acroform = writer._root_object["/AcroForm"]
    if isinstance(acroform, DictionaryObject):
        acroform[NameObject("/NeedAppearances")] = BooleanObject(True)

    font_dict = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    acroform[NameObject("/DR")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/Helv"): font_dict}),
    })

    fields_array = acroform.get("/Fields", ArrayObject())
    if not isinstance(fields_array, ArrayObject):
        fields_array = ArrayObject()

    for i, field_def in enumerate(fields):
        page_idx = field_def.get("page", 0)
        if page_idx >= len(writer.pages):
            continue

        page_obj = writer.pages[page_idx]
        mb = reader.pages[page_idx].mediabox
        pw = float(mb.width)
        ph = float(mb.height)
        ox = float(mb.left)
        oy = float(mb.bottom)

        x = ox + field_def["x_pct"] * pw
        w = field_def["w_pct"] * pw
        h = field_def["h_pct"] * ph
        y_top = oy + ph - field_def["y_pct"] * ph
        y_bottom = y_top - h

        field_name = field_def.get("name", f"Field_{i}")

        rect = ArrayObject([
            NumberObject(x), NumberObject(y_bottom),
            NumberObject(x + w), NumberObject(y_top),
        ])

        widget = DictionaryObject({
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/FT"): NameObject("/Tx"),
            NameObject("/T"): TextStringObject(field_name),
            NameObject("/Rect"): rect,
            NameObject("/DA"): create_string_object("/Helv 0 Tf 0 0 0 rg"),
            NameObject("/F"): NumberObject(4),
            NameObject("/Ff"): NumberObject(0),
            NameObject("/P"): page_obj.indirect_reference,
        })

        if field_def.get("type") == "date":
            js_code = 'event.value = util.printd("mm/dd/yyyy", new Date());'
            widget[NameObject("/AA")] = DictionaryObject({
                NameObject("/F"): DictionaryObject({
                    NameObject("/S"): NameObject("/JavaScript"),
                    NameObject("/JS"): create_string_object(js_code),
                }),
            })

        widget_ref = writer._add_object(widget)
        if "/Annots" not in page_obj:
            page_obj[NameObject("/Annots")] = ArrayObject()
        page_obj["/Annots"].append(widget_ref)
        fields_array.append(widget_ref)

    acroform[NameObject("/Fields")] = fields_array
    writer._root_object[NameObject("/AcroForm")] = acroform

    out = BytesIO()
    writer.write(out)
    return out.getvalue()
