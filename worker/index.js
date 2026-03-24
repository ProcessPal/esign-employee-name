import { PDFDocument, StandardFonts, rgb } from "pdf-lib";
import { encryptPdfPrintOnly } from "./pdf-encrypt.js";

const MAX_UPLOAD_SIZE = 50 * 1024 * 1024; // 50 MB

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/health") {
      return Response.json({ status: "ok" });
    }

    if (request.method === "POST" && url.pathname === "/api/prepare") {
      return handlePrepare(request);
    }

    if (request.method === "POST" && url.pathname === "/api/sign") {
      return handleSign(request);
    }

    // All other routes (GET /, static assets) are handled by [assets] in wrangler.toml
    return new Response("Not Found", { status: 404 });
  },
};

function jsonError(status, detail) {
  return Response.json({ detail }, { status });
}

async function readPdfFromForm(request) {
  const formData = await request.formData();
  const file = formData.get("file");
  const fieldsRaw = formData.get("fields");

  if (!file) return { error: jsonError(400, "No file uploaded") };

  const arrayBuf = await file.arrayBuffer();
  if (arrayBuf.byteLength > MAX_UPLOAD_SIZE) {
    return { error: jsonError(413, "File too large") };
  }

  const bytes = new Uint8Array(arrayBuf);
  if (bytes.length < 5 || String.fromCharCode(...bytes.slice(0, 5)) !== "%PDF-") {
    return { error: jsonError(400, "Invalid or corrupted PDF") };
  }

  let fieldDefs;
  try {
    fieldDefs = JSON.parse(fieldsRaw);
  } catch {
    return { error: jsonError(400, "Invalid field definitions") };
  }

  if (!fieldDefs || !fieldDefs.length) {
    return { error: jsonError(400, "No fields specified") };
  }

  return { bytes: arrayBuf, fieldDefs };
}

// --- /api/prepare: Add AcroForm text fields to PDF ---

async function handlePrepare(request) {
  const { bytes, fieldDefs, error } = await readPdfFromForm(request);
  if (error) return error;

  try {
    const pdfDoc = await PDFDocument.load(bytes);
    const form = pdfDoc.getForm();
    const pages = pdfDoc.getPages();

    for (const f of fieldDefs) {
      const pageIdx = f.page ?? 0;
      const page = pages[pageIdx];
      if (!page) continue;

      const { width, height } = page.getSize();
      const x = f.x_pct * width;
      const w = f.w_pct * width;
      const h = f.h_pct * height;
      const yTop = height - f.y_pct * height;
      const yBottom = yTop - h;

      const fieldName = f.name || `Field_${fieldDefs.indexOf(f)}`;
      const textField = form.createTextField(fieldName);
      textField.addToPage(page, {
        x,
        y: yBottom,
        width: w,
        height: h,
        borderWidth: 0,
        backgroundColor: rgb(1, 1, 1),
      });
    }

    const resultBytes = await pdfDoc.save();
    return new Response(resultBytes, {
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": 'attachment; filename="prepared_document.pdf"',
        "X-Fields-Added": String(fieldDefs.length),
      },
    });
  } catch (exc) {
    return jsonError(500, `Processing error: ${exc.message}`);
  }
}

// --- /api/sign: Stamp text onto PDF pages (flat, non-editable) ---

async function handleSign(request) {
  const { bytes, fieldDefs, error } = await readPdfFromForm(request);
  if (error) return error;

  const emptyNames = fieldDefs.filter(
    (f) => f.type === "name" && !(f.value || "").trim()
  );
  if (emptyNames.length > 0) {
    return jsonError(422, "All signature fields must have values");
  }

  // Verification metadata
  const clientIp =
    request.headers.get("cf-connecting-ip") ||
    request.headers.get("x-forwarded-for") ||
    "unknown";
  const userAgent = request.headers.get("user-agent") || "unknown";
  const timestamp = new Date().toISOString().replace("T", " ").split(".")[0] + " UTC";
  const hashBuf = await crypto.subtle.digest("SHA-256", bytes);
  const docHash = [...new Uint8Array(hashBuf)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");

  try {
    const pdfDoc = await PDFDocument.load(bytes);
    const pages = pdfDoc.getPages();
    const fontBold = await pdfDoc.embedFont(StandardFonts.HelveticaBold);
    const fontRegular = await pdfDoc.embedFont(StandardFonts.Helvetica);

    // Stamp field values onto pages
    for (const f of fieldDefs) {
      const value = (f.value || "").trim();
      if (!value) continue;

      const page = pages[f.page];
      if (!page) continue;

      const { width, height } = page.getSize();
      const x = f.x_pct * width;
      const h = f.h_pct * height;
      const yTop = height - f.y_pct * height;
      const yBaseline = yTop - h * 0.75;
      const fontSize = Math.min(h * 0.7, 14);

      page.drawText(value, {
        x,
        y: yBaseline,
        size: fontSize,
        font: fontBold,
        color: rgb(0, 0, 0),
      });
    }

    // Verification footer on the last signed page
    const signedPages = [...new Set(fieldDefs.map((f) => f.page))].sort((a, b) => a - b);
    const lastSignedPage = signedPages[signedPages.length - 1];

    if (lastSignedPage !== undefined && lastSignedPage < pages.length) {
      const vpage = pages[lastSignedPage];
      const { width: vpw } = vpage.getSize();

      const signers = fieldDefs
        .filter((f) => f.type === "name" && f.value)
        .map((f) => f.value);
      const signerText = signers.length ? signers.join(", ") : "N/A";

      const fs = 6.5;
      const lh = 8.5;
      const margin = 36;
      const yStart = 42;

      const boxX = margin - 4;
      const boxY = yStart - 6;
      const boxW = vpw - 72 + 8;
      const boxH = lh * 5 + 10;

      vpage.drawRectangle({
        x: boxX,
        y: boxY,
        width: boxW,
        height: boxH,
        color: rgb(0.95, 0.95, 0.95),
        borderColor: rgb(0.8, 0.8, 0.8),
        borderWidth: 0.5,
      });

      let truncatedUa = userAgent;
      if (truncatedUa.length > 80) truncatedUa = truncatedUa.slice(0, 77) + "...";

      const shortHash = docHash.slice(0, 16) + "..." + docHash.slice(-16);
      const lines = [
        `eSign Verification  |  Signed by: ${signerText}`,
        `Timestamp: ${timestamp}  |  IP: ${clientIp}`,
        `Device: ${truncatedUa}`,
        `Document Hash (SHA-256): ${shortHash}`,
      ];

      let yCur = yStart + lh * 3 + 2;
      for (let i = 0; i < lines.length; i++) {
        vpage.drawText(lines[i], {
          x: margin,
          y: yCur,
          size: i === 0 ? fs + 1 : fs,
          font: fontRegular,
          color: rgb(0, 0, 0),
        });
        yCur -= lh;
      }
    }

    // Encrypt with print-only permissions (no user password, random owner password)
    const unencryptedBytes = await pdfDoc.save();
    const resultBytes = await encryptPdfPrintOnly(unencryptedBytes);
    return new Response(resultBytes, {
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": 'attachment; filename="signed_document.pdf"',
        "X-Fields-Signed": String(fieldDefs.length),
      },
    });
  } catch (exc) {
    return jsonError(500, `Processing error: ${exc.message}`);
  }
}
