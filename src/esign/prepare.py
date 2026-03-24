"""PDF e-sign preparation and signing using pypdf forms + flattening."""

from __future__ import annotations

import hashlib
import json as _json
import secrets
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


# ---------------------------------------------------------------------------
# PREPARE: Add fillable form fields + metadata to a PDF
# ---------------------------------------------------------------------------


def embed_field_metadata(pdf_bytes: bytes, fields: list[dict]) -> bytes:
    """Prepare a PDF for signing: add fillable form fields + hidden metadata.

    - Name fields: fillable text fields (signer types their name)
    - Date fields: fillable text field pre-filled with today's date
    - No encryption (signer must be able to open and fill on any device)
    - Hidden metadata stores field definitions for the web app signing flow
    """
    from datetime import date

    reader = PdfReader(BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)

    # Store metadata for web app
    writer.add_metadata({
        "/ESignFields": _json.dumps(fields),
        "/ESignVersion": "1.0",
    })

    # Create AcroForm
    if "/AcroForm" not in writer._root_object:
        writer._root_object[NameObject("/AcroForm")] = DictionaryObject()

    acroform = writer._root_object["/AcroForm"]
    acroform[NameObject("/NeedAppearances")] = BooleanObject(True)

    font_dict = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    acroform[NameObject("/DR")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/Helv"): font_dict}),
    })

    fields_array = ArrayObject()
    today = date.today().strftime("%m/%d/%Y")
    name_field_names = []
    date_field_names = []

    for i, f in enumerate(fields):
        page_idx = f.get("page", 0)
        if page_idx >= len(writer.pages):
            continue

        page_obj = writer.pages[page_idx]
        mb = reader.pages[page_idx].mediabox
        pw, ph = float(mb.width), float(mb.height)
        ox, oy = float(mb.left), float(mb.bottom)

        x = ox + f["x_pct"] * pw
        w = f["w_pct"] * pw
        h = f["h_pct"] * ph
        y_top = oy + ph - f["y_pct"] * ph
        y_bottom = y_top - h

        field_name = f.get("name", f"Field_{i}")
        is_date = f.get("type") == "date"

        if is_date:
            bc = ArrayObject([NumberObject(0.02), NumberObject(0.59), NumberObject(0.41)])
            bg = ArrayObject([NumberObject(0.93), NumberObject(1.0), NumberObject(0.95)])
            date_field_names.append(field_name)
        else:
            bc = ArrayObject([NumberObject(0.15), NumberObject(0.39), NumberObject(0.92)])
            bg = ArrayObject([NumberObject(0.93), NumberObject(0.95), NumberObject(1.0)])
            name_field_names.append(field_name)

        widget = DictionaryObject({
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/FT"): NameObject("/Tx"),
            NameObject("/T"): TextStringObject(field_name),
            NameObject("/Rect"): ArrayObject([
                NumberObject(x), NumberObject(y_bottom),
                NumberObject(x + w), NumberObject(y_top),
            ]),
            NameObject("/DA"): create_string_object("/Helv 12 Tf 0 0 0 rg"),
            NameObject("/F"): NumberObject(4),
            NameObject("/Ff"): NumberObject(0),  # All fields fillable
            NameObject("/P"): page_obj.indirect_reference,
            NameObject("/MK"): DictionaryObject({
                NameObject("/BC"): bc,
                NameObject("/BG"): bg,
            }),
        })

        # Pre-fill date fields with today's date
        if is_date:
            widget[NameObject("/V")] = TextStringObject(today)
            widget[NameObject("/TU")] = TextStringObject("Date")

        if not is_date:
            widget[NameObject("/TU")] = TextStringObject("Type your name here to sign")

        widget_ref = writer._add_object(widget)
        if "/Annots" not in page_obj:
            page_obj[NameObject("/Annots")] = ArrayObject()
        page_obj["/Annots"].append(widget_ref)
        fields_array.append(widget_ref)

    # JavaScript: when name field loses focus → update date + lock all fields
    if name_field_names and date_field_names:
        js_parts = []
        for dn in date_field_names:
            js_parts.append(f'var d=this.getField("{dn}");if(d){{d.value=util.printd("mm/dd/yyyy",new Date());d.readonly=true;}}')
        for nn in name_field_names:
            js_parts.append(f'var s=this.getField("{nn}");if(s)s.readonly=true;')
        js_code = " ".join(js_parts)

        for item in fields_array:
            fobj = item.get_object()
            fname = str(fobj.get("/T", ""))
            if fname in name_field_names:
                fobj[NameObject("/AA")] = DictionaryObject({
                    NameObject("/Bl"): DictionaryObject({
                        NameObject("/S"): NameObject("/JavaScript"),
                        NameObject("/JS"): create_string_object(js_code),
                    }),
                })

    acroform[NameObject("/Fields")] = fields_array
    writer._root_object[NameObject("/AcroForm")] = acroform

    norm_buf = BytesIO()
    writer.write(norm_buf)

    # --- Certify with pyHanko: MDP = FILL_FORMS (only form filling allowed) ---
    from pathlib import Path as _Path
    from pyhanko.sign import signers as _signers
    from pyhanko.sign.fields import MDPPerm as _MDPPerm
    from pyhanko.sign.fields import SigFieldSpec as _SigFieldSpec
    from pyhanko.sign.fields import append_signature_field as _append_sig
    from pyhanko.sign.signers.pdf_signer import PdfSigner as _PdfSigner
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter as _IW

    cert_dir = _Path(__file__).resolve().parent.parent.parent / "certs"
    key_path = cert_dir / "esign-key.pem"
    cert_path = cert_dir / "esign-cert.pem"
    if not key_path.exists() or not cert_path.exists():
        _generate_self_signed_cert(cert_dir)

    signer = _signers.SimpleSigner.load(str(key_path), str(cert_path))
    iw = _IW(BytesIO(norm_buf.getvalue()))
    _append_sig(iw, _SigFieldSpec(sig_field_name="DocCert"))

    meta = _signers.PdfSignatureMetadata(
        field_name="DocCert",
        md_algorithm="sha256",
        certify=True,
        docmdp_permissions=_MDPPerm.FILL_FORMS,
    )
    pdf_signer = _PdfSigner(meta, signer=signer)
    out = BytesIO()
    pdf_signer.sign_pdf(iw, output=out)
    return out.getvalue()


def _generate_self_signed_cert(cert_dir):
    """Generate a self-signed certificate for document certification."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from datetime import timedelta

    cert_dir.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "eSign Document Certification")]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "eSign Document Certification")]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )
    (cert_dir / "esign-key.pem").write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption())
    )
    (cert_dir / "esign-cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def read_field_metadata(pdf_bytes: bytes) -> list[dict] | None:
    """Read embedded field positions from PDF metadata."""
    reader = PdfReader(BytesIO(pdf_bytes))
    metadata = reader.metadata
    if not metadata:
        return None
    raw = metadata.get("/ESignFields")
    if not raw:
        return None
    try:
        return _json.loads(str(raw))
    except (_json.JSONDecodeError, TypeError):
        return None


# ---------------------------------------------------------------------------
# SIGN: Flatten filled form fields + add verification + lock
# ---------------------------------------------------------------------------


def sign_and_lock_pdf(
    pdf_bytes: bytes,
    verification: dict | None = None,
) -> bytes:
    """Read filled form fields, flatten them into page content, add verification, lock.

    This is the "sign" step: takes a filled PDF (from any viewer) and produces
    a permanently locked document.

    Uses pypdf's native flatten: update_page_form_field_values(flatten=True)
    then remove_annotations to strip all widgets.
    """
    reader = PdfReader(BytesIO(pdf_bytes))

    # Read current field values before flattening
    filled_values = {}
    if reader.get_form_text_fields():
        filled_values = reader.get_form_text_fields()

    # Use clone_from to preserve AcroForm for flattening
    writer = PdfWriter(clone_from=BytesIO(pdf_bytes))

    # Flatten: burn field values into page content
    for page in writer.pages:
        writer.update_page_form_field_values(page, fields={}, auto_regenerate=False, flatten=True)

    # Remove all form widget annotations
    writer.remove_annotations(subtypes="/Widget")

    # Remove AcroForm
    if "/AcroForm" in writer._root_object:
        del writer._root_object[NameObject("/AcroForm")]

    # Add verification page
    if verification:
        doc_hash = hashlib.sha256(pdf_bytes).hexdigest()
        _add_verification_page(writer, filled_values, verification, doc_hash)

    # Lock with encryption: print only, no editing
    owner_pwd = secrets.token_hex(32)
    writer.encrypt(
        user_password="",
        owner_password=owner_pwd,
        permissions_flag=0b0000_0000_0000_0100,  # print only
    )

    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def stamp_fields_onto_pdf(
    pdf_bytes: bytes,
    fields: list[dict],
    verification: dict | None = None,
) -> bytes:
    """Stamp text values directly onto PDF pages (web app signing flow).

    For when signing happens in the web UI, not in a native PDF viewer.
    """
    reader = PdfReader(BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)

    doc_hash = hashlib.sha256(pdf_bytes).hexdigest()

    fields_by_page: dict[int, list[dict]] = {}
    for f in fields:
        fields_by_page.setdefault(f.get("page", 0), []).append(f)

    for page_idx, page_fields in fields_by_page.items():
        if page_idx >= len(writer.pages):
            continue

        page = writer.pages[page_idx]
        mb = reader.pages[page_idx].mediabox
        pw, ph = float(mb.width), float(mb.height)
        ox, oy = float(mb.left), float(mb.bottom)

        font_key = _ensure_font_on_page(page, writer)
        commands = ["q"]

        for f in page_fields:
            value = f.get("value", "").strip()
            if not value:
                continue
            x = ox + f["x_pct"] * pw
            h = f["h_pct"] * ph
            y_top = oy + ph - f["y_pct"] * ph
            y_baseline = y_top - h * 0.75
            font_size = min(h * 0.7, 14)
            escaped = _escape_pdf_string(value)
            commands.append("BT")
            commands.append(f"/{font_key} {font_size:.1f} Tf")
            commands.append(f"{x:.2f} {y_baseline:.2f} Td")
            commands.append(f"({escaped}) Tj")
            commands.append("ET")

        commands.append("Q")
        _append_content_stream(page, writer, "\n".join(commands))

    if verification:
        _add_verification_page(writer, {}, verification, doc_hash)

    owner_pwd = secrets.token_hex(32)
    writer.encrypt(
        user_password="",
        owner_password=owner_pwd,
        permissions_flag=0b0000_0000_0000_0100,
    )

    out = BytesIO()
    writer.write(out)
    return out.getvalue()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _escape_pdf_string(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _ensure_font_on_page(page, writer) -> str:
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
        font_ref = writer._add_object(DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica-Bold"),
        }))
        fonts[NameObject(f"/{font_key}")] = font_ref
    return font_key


def _ensure_verification_font(page, writer) -> str:
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
        font_ref = writer._add_object(DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }))
        fonts[NameObject(f"/{font_key}")] = font_ref
    return font_key


def _append_content_stream(page, writer, stream_data: str):
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


def _add_verification_page(writer, filled_values, verification, doc_hash):
    writer.add_blank_page(width=612, height=792)
    vpage = writer.pages[-1]
    _ensure_font_on_page(vpage, writer)
    _ensure_verification_font(vpage, writer)

    ip = _escape_pdf_string(verification.get("ip", "unknown"))
    ua = verification.get("user_agent", "unknown")
    if len(ua) > 90:
        ua = ua[:87] + "..."
    ua = _escape_pdf_string(ua)
    ts = _escape_pdf_string(verification.get("timestamp", "unknown"))
    dh_full = _escape_pdf_string(doc_hash)

    signers = []
    for k, v in filled_values.items():
        if v and "date" not in k.lower():
            signers.append(str(v))
    signer_text = _escape_pdf_string(", ".join(signers)) if signers else "N/A"

    dates = []
    for k, v in filled_values.items():
        if v and "date" in k.lower():
            dates.append(str(v))
    date_text = _escape_pdf_string(dates[0]) if dates else "N/A"

    cmds = ["q"]
    cmds.append("BT /ESigF1 16 Tf 72 720 Td (eSign Verification Certificate) Tj ET")
    cmds.append("0.3 0.3 0.3 RG 0.5 w 72 712 468 0 re S")

    y = 685
    details = [
        ("Signed By", signer_text),
        ("Date Signed", date_text),
        ("Signing Timestamp (UTC)", ts),
        ("Signer IP Address", ip),
        ("Signer Device", ua),
        ("Original Document Hash (SHA-256)", ""),
    ]
    for label, value in details:
        cmds.append(f"BT /ESigF2 9 Tf 0.4 0.4 0.4 rg 72 {y} Td ({_escape_pdf_string(label)}:) Tj ET")
        if value:
            cmds.append(f"BT /ESigF1 11 Tf 0 0 0 rg 72 {y - 14} Td ({value}) Tj ET")
        y -= 38

    cmds.append(f"BT /ESigF2 7.5 Tf 0 0 0 rg 72 {y + 20} Td ({dh_full}) Tj ET")
    y -= 25
    cmds.append(f"0.8 0.8 0.8 RG 0.5 w 72 {y} 468 0 re S")
    y -= 20

    for note in [
        "This document was electronically signed using eSign.",
        "The signature and date were permanently embedded. This PDF is locked against editing.",
        "The document hash can verify the original document's integrity.",
    ]:
        cmds.append(f"BT /ESigF2 8 Tf 0.35 0.35 0.35 rg 72 {y} Td ({_escape_pdf_string(note)}) Tj ET")
        y -= 12

    cmds.append("Q")
    _append_content_stream(vpage, writer, "\n".join(cmds))
