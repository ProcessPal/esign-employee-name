# pyHanko & PDF e-Signing: Technical Research Report

**Date:** 2026-03-24
**Research Focus:** Building a PDF e-signing application with pyHanko, text coordinate extraction, and signature field management
**Target:** Practical code patterns for production use

---

## 1. pyHanko Signature Fields (Core API)

### 1.1 SigFieldSpec: Creating Signature Placeholders

**Purpose:** Define a signature field container (placeholder) that will appear on the PDF. Creating a field ≠ signing; fields are empty slots awaiting signatures.

#### Basic Invisible Field
```python
from pyhanko.sign.fields import SigFieldSpec, append_signature_field
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

# Create invisible signature field
with open('document.pdf', 'rb+') as doc:
    w = IncrementalPdfFileWriter(doc)
    append_signature_field(w, SigFieldSpec(sig_field_name="Sig1"))
    w.write_in_place()
```

#### Visible Field with Positioned Box
```python
# Create visible signature field at specific coordinates
sig_field = SigFieldSpec(
    sig_field_name="VisibleSig",
    on_page=0,  # Page index (0-based)
    box=(10, 74, 140, 134)  # (x1, y1, x2, y2) in Cartesian coords
)
```

#### SigFieldSpec Parameters

| Parameter | Type | Required | Notes |
|-----------|------|----------|-------|
| `sig_field_name` | str | Yes | Field identifier; **cannot contain periods (.)** |
| `on_page` | int | No | Page index (0-based); default: 0 |
| `box` | tuple(4) | No | Bounding box `(x1, y1, x2, y2)` in Cartesian; origin at **bottom-left**, y-axis runs upward |
| `seed_value_dict` | dict | No | Seed value restrictions (hash algorithm, certs, timestamps) |
| `field_mdp_spec` | FieldMDPSpec | No | Field modification detection policy |
| `doc_mdp_update_value` | MDPPerm | No | Document-level modification policy |

**Key constraint:** Box coordinates use PDF's bottom-left origin, not top-left (HTML/screen convention).

#### Advanced: Field with Modification Policy
```python
from pyhanko.sign import fields

sig_field = fields.SigFieldSpec(
    'Sig1',
    box=(10, 74, 140, 134),
    field_mdp_spec=fields.FieldMDPSpec(
        fields.FieldMDPAction.INCLUDE,
        fields=['NameField', 'DateField']  # Only these fields can be filled after signing
    ),
    doc_mdp_update_value=fields.MDPPerm.FORM_FILLING  # Allow form filling but no edits
)
```

---

### 1.2 append_signature_field(): Adding Fields to PDF

**Signature:**
```python
append_signature_field(w: IncrementalPdfFileWriter, sig_field_spec: SigFieldSpec)
```

**Returns:** None (modifies writer in-place)

#### Workflow: Add Multiple Fields
```python
from pyhanko.sign.fields import SigFieldSpec, append_signature_field
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

with open('document.pdf', 'rb+') as doc:
    w = IncrementalPdfFileWriter(doc)

    # Add signature field 1 on page 0
    append_signature_field(w, SigFieldSpec(
        sig_field_name="Sig1",
        on_page=0,
        box=(50, 700, 200, 750)
    ))

    # Add signature field 2 on page 1
    append_signature_field(w, SigFieldSpec(
        sig_field_name="Sig2",
        on_page=1,
        box=(50, 700, 200, 750)
    ))

    # Write all changes back to PDF
    w.write_in_place()
```

**Key points:**
- Multiple calls to `append_signature_field()` are cumulative
- Call `write_in_place()` once after all fields added
- Does NOT modify the PDF's content; only adds form fields
- Safe to call on PDFs with existing signatures

---

### 1.3 IncrementalPdfFileWriter: Adding Fields Without Signing

**Purpose:** Modify a PDF incrementally without re-writing the entire document.

#### When to Use IncrementalPdfFileWriter

| Operation | Use IW? | Notes |
|-----------|---------|-------|
| Add empty signature fields | **Yes** | Preserves existing signatures |
| Add signature field + sign | **Yes** | Append field, then sign |
| Sign existing signature field | **Yes** | Incremental append |
| Modify content/layout | No | Requires full rewrite |

#### File Handling Pattern
```python
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign.fields import SigFieldSpec, append_signature_field

# Option 1: Modify in-place (file mode 'rb+')
with open('document.pdf', 'rb+') as doc:
    w = IncrementalPdfFileWriter(doc)
    append_signature_field(w, SigFieldSpec(sig_field_name="Sig1"))
    w.write_in_place()  # Overwrites original

# Option 2: Write to new file (file mode 'rb')
with open('document.pdf', 'rb') as doc:
    w = IncrementalPdfFileWriter(doc)
    append_signature_field(w, SigFieldSpec(sig_field_name="Sig1"))

with open('document-with-fields.pdf', 'wb') as out:
    w.write(out)
```

**Performance:** IncrementalPdfFileWriter streams changes incrementally; memory usage is constant regardless of PDF size.

---

### 1.4 Difference: Signature FIELD vs SIGNING

| Aspect | Field (SigFieldSpec) | Signing |
|--------|----------------------|---------|
| **Action** | Create empty placeholder | Add actual signature to field |
| **Result** | Unsignedfield appears on PDF | Field is filled with cryptographic data |
| **API** | `append_signature_field()` | `PdfSigner.sign()` |
| **Reversible** | Yes (remove field) | No (permanent on PDF) |
| **Count** | Multiple fields per page | One signature per field |
| **User sees** | "Sign here" box | "Signed on [date]" indicator |

#### Workflow: Add Field, Then Sign Later
```python
# Step 1: Add empty signature field (one-time setup)
with open('template.pdf', 'rb+') as doc:
    w = IncrementalPdfFileWriter(doc)
    append_signature_field(w, SigFieldSpec(
        sig_field_name="EmployeeSig",
        box=(50, 100, 300, 150)
    ))
    w.write_in_place()  # template.pdf now has a signature field

# Step 2: Sign the field later (when user is ready)
# ... (see signing section below)
```

---

## 2. PDF Text Coordinate Extraction

### 2.1 PyMuPDF (fitz) - Fast, Built-in

**Best for:** Quick text extraction with bounding boxes; no external dependencies.

#### Basic Text + Coordinates
```python
import fitz  # PyMuPDF

pdf = fitz.open('document.pdf')
page = pdf[0]  # First page

# Extract words with bounding boxes
words = page.get_text("words")  # Returns list of tuples
for word_tuple in words:
    x0, y0, x1, y1, text, block_no, line_no, word_no = word_tuple
    print(f"Word: '{text}' at ({x0}, {y0}) - ({x1}, {y1})")
```

**Returns format:** `(x0, y0, x1, y1, "word", block_no, line_no, word_no)`

#### Structured Dict Extraction
```python
import fitz

pdf = fitz.open('document.pdf')
page = pdf[0]

# Full structured data (blocks > lines > spans)
text_dict = page.get_text("dict")

for block in text_dict['blocks']:
    if block['type'] == 0:  # Text block
        for line in block['lines']:
            for span in line['spans']:
                text = span['text']
                bbox = span['bbox']  # (x0, y0, x1, y1)
                font_name = span['font']
                font_size = span['size']
                print(f"{text} | Font: {font_name} | Size: {font_size} | Box: {bbox}")
```

#### Find Text and Get Coordinates
```python
import fitz

pdf = fitz.open('document.pdf')
page = pdf[0]

# Search for text and get bounding boxes
search_results = page.search_for("Employee Name")  # Returns list of Rect objects
for rect in search_results:
    x0, y0, x1, y1 = rect  # or rect.x0, rect.y0, rect.x1, rect.y1
    print(f"Found 'Employee Name' at box: ({x0}, {y0}, {x1}, {y1})")
```

#### Coordinate System Note
- **PyMuPDF coordinates:** Top-left origin (y increases downward)
- **PDF coordinates:** Bottom-left origin (y increases upward)
- **Conversion:** `pdf_y = page_height - pymupdf_y`

---

### 2.2 pdfplumber - High-Level, User-Friendly

**Best for:** Precise text position detection; natural coordinate system (top-left).

#### Extract Words with Coordinates
```python
import pdfplumber

with pdfplumber.open('document.pdf') as pdf:
    page = pdf.pages[0]
    words = page.extract_words()

    for word in words:
        print(f"Word: {word['text']}")
        print(f"  x0={word['x0']}, top={word['top']}")  # Top-left origin
        print(f"  x1={word['x1']}, bottom={word['bottom']}")
```

**Word dictionary keys:**
```
{
  'text': 'Employee',
  'x0': 50.0,      # left edge
  'top': 100.0,    # top edge (origin at top)
  'x1': 120.0,     # right edge
  'bottom': 112.0, # bottom edge
  'doctop': 100.0, # document-relative top
}
```

#### Region-Based Text Extraction
```python
import pdfplumber

with pdfplumber.open('document.pdf') as pdf:
    page = pdf.pages[0]

    # Extract text within a region
    region = {
        'top': 100,
        'bottom': 150,
        'left': 50,
        'right': 400
    }

    text_in_region = page.crop(region).extract_text()
    print(text_in_region)
```

#### Find Text and Get Coordinates
```python
import pdfplumber
import re

with pdfplumber.open('document.pdf') as pdf:
    page = pdf.pages[0]

    # Extract all words
    words = page.extract_words()

    # Find specific text
    for word in words:
        if re.match(r'Employee|Signature', word['text']):
            print(f"Found '{word['text']}' at ({word['x0']}, {word['top']})")
```

**Pros:** Native top-left origin (no conversion needed); cleaner API

---

### 2.3 pdfminer.six - Low-Level, Character-Level Control

**Best for:** Fine-grained character extraction; complex layout analysis.

#### Character-Level Extraction with Coordinates
```python
from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTTextBox, LTChar

for page_layout in extract_pages('document.pdf', laparams=LAParams()):
    for element in page_layout:
        if isinstance(element, LTTextBox):
            for line in element:
                for char in line:
                    if isinstance(char, LTChar):
                        x0, y0, x1, y1 = char.bbox
                        print(f"Char: '{char.get_text()}' at bbox: {(x0, y0, x1, y1)}")
```

#### LAParams: Fine-Tuning Layout Analysis
```python
from pdfminer.layout import LAParams

# Customize character/line grouping
laparams = LAParams(
    line_overlap=0.5,      # Vertical overlap threshold (0-1)
    char_margin=2.0,       # Horizontal distance for grouping
    line_margin=0.5,       # Vertical distance for grouping
    word_margin=0.1,       # Space between words
    boxes_flow=0.5         # Box overlap threshold
)

for page_layout in extract_pages('document.pdf', laparams=laparams):
    # Process page
    pass
```

**Default LAParams work for ~80% of PDFs; tune if text grouping is incorrect.**

---

### 2.4 Comparison: PyMuPDF vs pdfplumber vs pdfminer.six

| Feature | PyMuPDF | pdfplumber | pdfminer.six |
|---------|---------|-----------|--------------|
| **Speed** | Fast | Medium | Slow |
| **Bounding boxes** | Yes | Yes | Yes |
| **Character-level** | No | No | Yes |
| **Coordinate origin** | Top-left | Top-left | Bottom-left |
| **Layout analysis** | Basic | Good | Excellent |
| **Setup** | Simple | Simple | Complex (LAParams) |
| **Best for** | Quick extraction | Text position | Fine control |

**Recommendation:** Start with **pdfplumber** (clean API, top-left origin); fall back to **PyMuPDF** if speed critical; use **pdfminer.six** for character-level control.

---

## 3. PDF Coordinate Systems

### 3.1 PDF Native Coordinates (Bottom-Left Origin)

All PDF specifications use:
- **Origin:** Bottom-left corner of page
- **X-axis:** Increases to the right (0 → page width)
- **Y-axis:** Increases upward (0 → page height)
- **Units:** Points (1 point = 1/72 inch)

**Example:** Letter size (8.5×11 inches) = 612×792 points

#### PDFGeometry
```python
# Letter page: 612×792 points
page_width = 612
page_height = 792

# Signature field at bottom-left
sig_box_pdf = (50, 50, 200, 100)  # Bottom-left region

# Signature field at top-left (converted)
pdf_top_y = page_height - 100  # 792 - 100 = 692
sig_box_pdf_top = (50, 692, 200, 742)
```

---

### 3.2 Conversion: Top-Left (Screens) ↔ Bottom-Left (PDF)

**Most text extraction libraries (PyMuPDF, pdfplumber) return top-left coordinates.**

#### Convert PyMuPDF (Top-Left) → PDF (Bottom-Left)
```python
import fitz

pdf = fitz.open('document.pdf')
page = pdf[0]
page_height = page.rect.height  # Get page height in points

# Extract text with top-left origin
text_dict = page.get_text("dict")

for block in text_dict['blocks']:
    if block['type'] == 0:
        for line in block['lines']:
            for span in line['spans']:
                x0, y0_topleft, x1, y1_topleft = span['bbox']

                # Convert to PDF coordinates (bottom-left origin)
                y0_pdf = page_height - y1_topleft
                y1_pdf = page_height - y0_topleft

                pdf_box = (x0, y0_pdf, x1, y1_pdf)
                print(f"PDF box: {pdf_box}")
```

#### Convert pdfplumber (Top-Left) → PDF (Bottom-Left)
```python
import pdfplumber

with pdfplumber.open('document.pdf') as pdf:
    page = pdf.pages[0]
    page_height = page.height

    words = page.extract_words()
    for word in words:
        x0 = word['x0']
        y0_topleft = word['top']
        x1 = word['x1']
        y1_topleft = word['bottom']

        # Convert to PDF coordinates
        y0_pdf = page_height - y1_topleft
        y1_pdf = page_height - y0_topleft

        pdf_box = (x0, y0_pdf, x1, y1_pdf)
        print(f"PDF box for '{word['text']}': {pdf_box}")
```

**General formula:**
```
pdf_y = page_height - screen_y
```

---

### 3.3 Common Page Sizes (in Points)

| Size | Width | Height | Notes |
|------|-------|--------|-------|
| Letter | 612 | 792 | US standard |
| A4 | 595 | 842 | International |
| Legal | 612 | 1008 | US legal |
| Tabloid | 792 | 1224 | Poster size |

---

## 4. pyHanko Signing API (PdfSigner)

### 4.1 PdfSigner: The Main Signing Interface

**Purpose:** Manage signing workflow, add signatures to signature fields, handle appearance/timestamps.

#### SimpleSigner: Certificate & Key Loading
```python
from pyhanko.sign import signers

# Load certificate and private key
cms_signer = signers.SimpleSigner.load(
    key_file='path/to/private-key.pem',
    cert_file='path/to/certificate.pem',
    ca_chain_files=('path/to/ca-bundle.pem',),  # Optional CA chain
    key_passphrase=b'password'  # Required if key is encrypted
)
```

#### Basic Signing Workflow
```python
from pyhanko.sign import signers, fields
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from io import BytesIO

# Step 1: Load signer
cms_signer = signers.SimpleSigner.load(
    'key.pem', 'cert.pem', key_passphrase=b'secret'
)

# Step 2: Create metadata for signature
meta = signers.PdfSignatureMetadata(
    field_name='Sig1'  # Must match an existing signature field
)

# Step 3: Create PdfSigner instance
pdf_signer = signers.PdfSigner(meta, signer=cms_signer)

# Step 4: Sign the PDF
with open('document-with-fields.pdf', 'rb') as doc_in:
    with open('signed.pdf', 'wb') as doc_out:
        pdf_signer.sign_pdf(doc_in, output=doc_out)
```

#### Signature Metadata Options
```python
from pyhanko.sign import signers

meta = signers.PdfSignatureMetadata(
    field_name='EmployeeSig',
    location='New York, NY',
    reason='Employee acknowledgment',
    signer_name='John Doe'
)
```

---

### 4.2 Appearance & Stamps: Customizing Signature Look

#### Text Stamp (Simple)
```python
from pyhanko.sign import signers
from pyhanko.pdf_utils import text
from pyhanko import stamp

text_stamp = stamp.TextStampStyle(
    stamp_text='Signed by: %(signer)s\nDate: %(ts)s'
)

pdf_signer = signers.PdfSigner(
    meta,
    signer=cms_signer,
    stamp_style=text_stamp
)
```

#### QR Code Stamp (With URL)
```python
from pyhanko import stamp

qr_stamp = stamp.QRStampStyle(
    stamp_text='Signed by: %(signer)s\nDate: %(ts)s',
    url_parameters={'file': 'document.pdf'}
)

pdf_signer = signers.PdfSigner(
    meta,
    signer=cms_signer,
    stamp_style=qr_stamp
)
```

---

### 4.3 Timestamp Integration

```python
from pyhanko.sign import signers
from pyhanko.sign.timestamps import HTTPTimeStamper

# Use external TSA (Time Stamp Authority)
timestamper = HTTPTimeStamper(
    url='http://timestamp.globalsign.com/tsa'
)

meta = signers.PdfSignatureMetadata(
    field_name='Sig1'
)

pdf_signer = signers.PdfSigner(
    meta,
    signer=cms_signer,
    timestamper=timestamper
)
```

---

### 4.4 Key Difference: Signature Field vs Signing

```python
# Adding a field (multiple times per page possible)
append_signature_field(w, SigFieldSpec(sig_field_name="Sig1", box=...))

# Signing a field (one signature per field)
pdf_signer.sign_pdf(doc_in, output=doc_out)  # Fills one field with signature
```

---

## 5. Certificate & Key Generation (For Demo/Testing)

**Note:** pyHanko does NOT provide certificate generation. Use `cryptography` library.

### 5.1 Generate Self-Signed Certificate + Key

```python
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding, PrivateFormat, NoEncryption, PublicFormat
)
from cryptography.x509.oid import NameOID
import datetime

# Step 1: Generate RSA private key
private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048
)

# Step 2: Build certificate subject/issuer
subject = issuer = x509.Name([
    x509.NameAttribute(NameOID.COMMON_NAME, u"Test Signer"),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"Test Org"),
    x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
])

# Step 3: Create certificate
cert = (
    x509.CertificateBuilder()
    .subject_name(subject)
    .issuer_name(issuer)
    .public_key(private_key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(datetime.datetime.utcnow())
    .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
    .add_extension(
        x509.BasicConstraints(ca=False, path_length=None),
        critical=True,
    )
    .sign(private_key, hashes.SHA256())
)

# Step 4: Save private key
with open('demo-key.pem', 'wb') as f:
    f.write(private_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=NoEncryption()
    ))

# Step 5: Save certificate
with open('demo-cert.pem', 'wb') as f:
    f.write(cert.public_bytes(Encoding.PEM))
```

**Result:** `demo-key.pem` (unencrypted) and `demo-cert.pem`

**For production:** Use `cryptography` + secure key storage (HSM, vault).

---

## 6. FastAPI Patterns: PDF Upload & Processing

### 6.1 Basic File Upload Handler

```python
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse
import tempfile
import os

app = FastAPI()

@app.post("/upload-pdf")
async def upload_pdf(file: UploadFile = File(...)):
    # Validate MIME type
    if file.content_type != 'application/pdf':
        return {"error": "File must be PDF"}

    # Save to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
        content = await file.read()
        tmp.write(content)
        temp_path = tmp.name

    try:
        # Process PDF (e.g., add signature fields)
        # ... your pyHanko code ...

        # Return modified PDF
        return FileResponse(temp_path, media_type='application/pdf')
    finally:
        os.unlink(temp_path)  # Clean up
```

### 6.2 Add Signature Fields via API

```python
from fastapi import FastAPI, UploadFile, File, Form
from pyhanko.sign.fields import SigFieldSpec, append_signature_field
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from io import BytesIO
import tempfile

app = FastAPI()

@app.post("/add-signature-field")
async def add_signature_field(
    file: UploadFile = File(...),
    x: float = Form(...),
    y: float = Form(...),
    width: float = Form(...),
    height: float = Form(...)
):
    content = await file.read()

    # Create signature field
    sig_field = SigFieldSpec(
        sig_field_name=f"Sig_{int(x)}_{int(y)}",
        box=(x, y, x + width, y + height)
    )

    # Add field to PDF
    with BytesIO(content) as pdf_in:
        w = IncrementalPdfFileWriter(pdf_in)
        append_signature_field(w, sig_field)

        result = BytesIO()
        w.write(result)
        result.seek(0)

        return {
            "pdf": result.getvalue().hex(),  # Base64-encoded PDF
            "field_name": sig_field.sig_field_name
        }
```

### 6.3 Sign PDF via API

```python
from fastapi import FastAPI, UploadFile, File
from pyhanko.sign import signers
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from io import BytesIO

app = FastAPI()

# Pre-load signer (once at startup)
signer = signers.SimpleSigner.load(
    'demo-key.pem', 'demo-cert.pem'
)

@app.post("/sign-pdf")
async def sign_pdf(file: UploadFile = File(...)):
    content = await file.read()

    meta = signers.PdfSignatureMetadata(field_name='Sig1')
    pdf_signer = signers.PdfSigner(meta, signer=signer)

    result = BytesIO()
    pdf_signer.sign_pdf(BytesIO(content), output=result)
    result.seek(0)

    return FileResponse(result, media_type='application/pdf')
```

---

## 7. Best Practices

### 7.1 Handling Different Page Sizes

**Always query page height before setting box coordinates:**

```python
import fitz
from pyhanko.sign.fields import SigFieldSpec

pdf = fitz.open('document.pdf')
page = pdf[0]
page_height = page.rect.height  # Get actual height

# Position signature 50 points from bottom, 100 points wide
sig_box = (50, 50, 150, 100)  # Will work on any page size
```

---

### 7.2 Error Handling: Malformed PDFs

```python
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfReadError

try:
    with open('document.pdf', 'rb+') as doc:
        w = IncrementalPdfFileWriter(doc)
        append_signature_field(w, SigFieldSpec(sig_field_name="Sig1"))
        w.write_in_place()
except PdfReadError as e:
    print(f"Malformed PDF: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")
```

---

### 7.3 Workflow: Add Fields First, Sign Later

**Recommended pattern for e-signature app:**

1. **Upload** → Add signature fields at specified coordinates
2. **Download** → User receives PDF with empty signature boxes
3. **Sign** → User signs via web UI or separate process
4. **Return** → Signed PDF returned to server

```python
# Workflow:
# 1. api/upload → append_signature_field(w, SigFieldSpec(...))
# 2. api/download → return PDF with fields
# 3. api/sign → PdfSigner.sign_pdf(...)
# 4. api/get-signed → return signed PDF
```

---

### 7.4 Coordinate Conversion Helper

```python
def screen_to_pdf_coords(x_screen, y_screen, page_height):
    """Convert top-left origin (screen) to bottom-left origin (PDF)."""
    y_pdf = page_height - y_screen
    return (x_screen, y_pdf)

def pdf_to_screen_coords(x_pdf, y_pdf, page_height):
    """Convert bottom-left origin (PDF) to top-left origin (screen)."""
    y_screen = page_height - y_pdf
    return (x_screen, y_screen)
```

---

## 8. Practical Code Example: Complete Workflow

```python
#!/usr/bin/env python3
"""
Complete PDF e-signing workflow:
1. Load template PDF
2. Extract text positions
3. Add signature fields at those positions
4. Sign the PDF
"""

import fitz
from pyhanko.sign.fields import SigFieldSpec, append_signature_field
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import signers
from io import BytesIO

def add_signature_fields_at_text(pdf_path, search_text, cert_path, key_path):
    """Add signature fields where specific text appears."""

    # Step 1: Find text positions
    pdf = fitz.open(pdf_path)
    page = pdf[0]
    page_height = page.rect.height

    search_results = page.search_for(search_text)
    if not search_results:
        raise ValueError(f"Text '{search_text}' not found")

    # Get bounding box of found text
    rect = search_results[0]
    x0, y0_topleft, x1, y1_topleft = rect

    # Convert to PDF coordinates (bottom-left)
    y0_pdf = page_height - y1_topleft
    y1_pdf = page_height - y0_topleft

    # Add padding around text
    padding = 10
    sig_box = (x0 - padding, y0_pdf - padding, x1 + padding, y1_pdf + padding)

    # Step 2: Add signature field
    with open(pdf_path, 'rb+') as doc:
        w = IncrementalPdfFileWriter(doc)
        append_signature_field(w, SigFieldSpec(
            sig_field_name="EmployeeSig",
            box=sig_box
        ))
        w.write_in_place()

    # Step 3: Sign the field
    cms_signer = signers.SimpleSigner.load(key_path, cert_path)
    meta = signers.PdfSignatureMetadata(
        field_name='EmployeeSig',
        signer_name='Employee'
    )
    pdf_signer = signers.PdfSigner(meta, signer=cms_signer)

    with open(pdf_path, 'rb') as doc_in:
        with open(pdf_path.replace('.pdf', '-signed.pdf'), 'wb') as doc_out:
            pdf_signer.sign_pdf(doc_in, output=doc_out)

# Usage
add_signature_fields_at_text(
    'employee-form.pdf',
    'Employee Signature:',
    'demo-cert.pem',
    'demo-key.pem'
)
```

---

## 9. Library Installation & Dependencies

```bash
# Core libraries
pip install pyhanko PyMuPDF pdfplumber pdfminer.six

# Certificate generation
pip install cryptography

# Web framework
pip install fastapi uvicorn python-multipart

# Optional: async HTTP
pip install aiofiles

# Optional: timestamp support
pip install requests
```

**Requirements summary:**
- **pyHanko 0.20.0+** (latest stable as of 2025)
- **PyMuPDF 1.20.0+** (for fast text extraction)
- **pdfplumber 0.11.0+** (for text position detection)
- **cryptography 40.0+** (for certificate generation)

---

## Unresolved Questions

1. **Does pyHanko support LTV (Long-Term Validation) signatures out-of-box?** - Documentation mentions PAdES-B-LTA but integration details unclear for production use.

2. **How to handle PDF forms with existing AcroForm fields?** - Tested with signature fields only; behavior with text input fields needs clarification.

3. **What is the maximum field count per page without performance degradation?** - No documented limits; needs empirical testing.

4. **Can multiple signatures be visible on the same page?** - Yes (different field names), but overlap behavior not documented.

5. **Does FastAPI's UploadFile handle large PDFs (100MB+) efficiently?** - Documentation mentions streaming; needs benchmarking.

---

## Source References

- [pyHanko Signature Fields Documentation](https://docs.pyhanko.eu/en/latest/lib-guide/sig-fields.html)
- [pyHanko Signing Functionality](https://docs.pyhanko.eu/en/latest/lib-guide/signing.html)
- [PyMuPDF Text Extraction Recipes](https://pymupdf.readthedocs.io/en/latest/recipes-text.html)
- [PyMuPDF Text Extraction Details](https://pymupdf.readthedocs.io/en/latest/app1.html)
- [pdfplumber Documentation](https://pdfplumber.net/)
- [pdfminer.six Documentation](https://pdfminersix.readthedocs.io/en/latest/topic/converting_pdf_to_text.html)
- [PDF Coordinate Systems - Apryse](https://apryse.com/blog/pdf-coordinates-and-pdf-processing)
- [FastAPI File Uploads](https://fastapi.tiangolo.com/reference/uploadfile/)
- [FastAPI File Upload Patterns 2025](https://betterstack.com/community/guides/scaling-python/uploading-files-using-fastapi/)
