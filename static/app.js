const pdfjsLib = await import("https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.9.155/pdf.min.mjs");
pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.9.155/pdf.worker.min.mjs";

// --- State ---
let pdfDoc = null;
let pdfBytes = null;
let currentPage = 1;
let totalPages = 0;
let scale = 1.5;
let activeFieldType = "name";
let fields = []; // { id, type, page, xPct, yPct, wPct, hPct, value }
let fieldIdCounter = 0;
let mode = "place"; // "place" or "sign"

// Drawing state
let isDrawing = false;
let drawStart = { x: 0, y: 0 };
let drawingRect = null;
let editingFieldId = null;

// --- DOM refs ---
const uploadScreen = document.getElementById("upload-screen");
const editorScreen = document.getElementById("editor-screen");
const dropZone = document.getElementById("drop-zone");
const fileInput = document.getElementById("file-input");
const canvas = document.getElementById("pdf-canvas");
const ctx = canvas.getContext("2d");
const overlay = document.getElementById("field-overlay");
const pageInfo = document.getElementById("page-info");
const btnPrev = document.getElementById("btn-prev-page");
const btnNext = document.getElementById("btn-next-page");
const btnPrepare = document.getElementById("btn-prepare");
const btnSign = document.getElementById("btn-sign");
const btnReset = document.getElementById("btn-reset");
const btnNameField = document.getElementById("btn-name-field");
const btnDateField = document.getElementById("btn-date-field");
const fieldListEl = document.getElementById("field-list");
const fieldCountEl = document.getElementById("field-count");
const modeLabel = document.getElementById("mode-label");

// --- Upload handling ---
dropZone.addEventListener("click", (e) => {
  if (e.target === fileInput) return; // Don't re-trigger from the input itself
  fileInput.click();
});
fileInput.addEventListener("change", (e) => {
  if (e.target.files[0]) loadPdf(e.target.files[0]);
});
dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropZone.classList.add("dragover");
});
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("dragover");
  if (e.dataTransfer.files[0]) loadPdf(e.dataTransfer.files[0]);
});

async function loadPdf(file) {
  const arrayBuf = await file.arrayBuffer();
  pdfBytes = new Uint8Array(arrayBuf);
  pdfDoc = await pdfjsLib.getDocument({ data: pdfBytes.slice() }).promise;
  totalPages = pdfDoc.numPages;
  currentPage = 1;
  fields = [];
  fieldIdCounter = 0;
  mode = "place";
  uploadScreen.classList.add("hidden");
  editorScreen.classList.remove("hidden");
  updateModeUI();
  await renderPage(currentPage);
  updatePageControls();
  updateFieldList();
}

// --- PDF rendering ---
async function renderPage(pageNum) {
  const page = await pdfDoc.getPage(pageNum);
  const viewport = page.getViewport({ scale });
  canvas.width = viewport.width;
  canvas.height = viewport.height;
  await page.render({ canvasContext: ctx, viewport }).promise;
  syncOverlay();
  renderFieldsOnPage();
}

function syncOverlay() {
  // Overlay must match the canvas DISPLAY size, not buffer size
  const rect = canvas.getBoundingClientRect();
  const container = document.getElementById("canvas-container");
  const cRect = container.getBoundingClientRect();
  overlay.style.left = (rect.left - cRect.left + container.scrollLeft) + "px";
  overlay.style.top = (rect.top - cRect.top + container.scrollTop) + "px";
  overlay.style.width = rect.width + "px";
  overlay.style.height = rect.height + "px";
}

function renderFieldsOnPage() {
  overlay.querySelectorAll(".placed-field").forEach((el) => el.remove());

  // Use display dimensions to convert percentages back to screen pixels
  const displayRect = canvas.getBoundingClientRect();
  const dw = displayRect.width;
  const dh = displayRect.height;

  fields
    .filter((f) => f.page === currentPage)
    .forEach((f) => {
      const sx = f.xPct * dw;
      const sy = f.yPct * dh;
      const sw = f.wPct * dw;
      const sh = f.hPct * dh;

      const el = document.createElement("div");
      el.className = `placed-field ${f.type}-field`;
      el.style.left = sx + "px";
      el.style.top = sy + "px";
      el.style.width = sw + "px";
      el.style.height = sh + "px";
      el.dataset.fieldId = f.id;

      if (mode === "sign") {
        if (f.type === "date") {
          // Date: NEVER editable. Shows timestamp only after name is signed.
          el.classList.add("locked");
          el.style.cursor = "not-allowed";
          if (f.value) {
            el.textContent = f.value;
            el.style.fontSize = Math.min(sh * 0.6, 14) + "px";
            el.classList.add("filled");
          } else {
            el.textContent = "Auto-fills when signed";
            el.style.fontSize = "9px";
            el.style.opacity = "0.5";
          }
        } else if (f.value) {
          // Name: signed
          el.textContent = f.value;
          el.style.fontSize = Math.min(sh * 0.6, 16) + "px";
          el.classList.add("filled");
          el.style.cursor = "pointer";
          el.addEventListener("click", (e) => { e.stopPropagation(); promptFieldValue(f); });
        } else {
          // Name: awaiting signature
          el.textContent = "Click to sign";
          el.style.fontSize = "11px";
          el.style.opacity = "0.7";
          el.style.cursor = "pointer";
          el.addEventListener("click", (e) => { e.stopPropagation(); promptFieldValue(f); });
        }
      } else {
        // In place mode, show type label + delete
        el.textContent = f.type === "name" ? "Name" : "Date";
        const delBtn = document.createElement("button");
        delBtn.className = "delete-btn";
        delBtn.textContent = "\u00d7";
        delBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          removeField(f.id);
        });
        el.appendChild(delBtn);
      }

      overlay.appendChild(el);
    });
}

// Re-sync overlay on scroll/resize
document.getElementById("canvas-container").addEventListener("scroll", syncOverlay);
window.addEventListener("resize", () => { syncOverlay(); renderFieldsOnPage(); });

// --- Page navigation ---
btnPrev.addEventListener("click", async () => {
  if (currentPage > 1) { currentPage--; await renderPage(currentPage); updatePageControls(); }
});
btnNext.addEventListener("click", async () => {
  if (currentPage < totalPages) { currentPage++; await renderPage(currentPage); updatePageControls(); }
});
function updatePageControls() {
  pageInfo.textContent = `Page ${currentPage} / ${totalPages}`;
  btnPrev.disabled = currentPage <= 1;
  btnNext.disabled = currentPage >= totalPages;
}

// --- Tool selection ---
btnNameField.addEventListener("click", () => setActiveFieldType("name"));
btnDateField.addEventListener("click", () => setActiveFieldType("date"));
function setActiveFieldType(type) {
  activeFieldType = type;
  btnNameField.classList.toggle("active", type === "name");
  btnDateField.classList.toggle("active", type === "date");
}

// --- Drawing fields ---
canvas.addEventListener("mousedown", (e) => {
  if (mode !== "place") return;
  const rect = canvas.getBoundingClientRect();
  drawStart.x = e.clientX - rect.left;
  drawStart.y = e.clientY - rect.top;
  isDrawing = true;
  drawingRect = document.createElement("div");
  drawingRect.className = `drawing-rect ${activeFieldType}-field`;
  overlay.appendChild(drawingRect);
});

canvas.addEventListener("mousemove", (e) => {
  if (!isDrawing || !drawingRect) return;
  const rect = canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;
  const x = Math.min(drawStart.x, mx);
  const y = Math.min(drawStart.y, my);
  const w = Math.abs(mx - drawStart.x);
  const h = Math.abs(my - drawStart.y);
  drawingRect.style.left = x + "px";
  drawingRect.style.top = y + "px";
  drawingRect.style.width = w + "px";
  drawingRect.style.height = h + "px";
});

canvas.addEventListener("mouseup", (e) => {
  if (!isDrawing) return;
  isDrawing = false;
  const rect = canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;
  const x = Math.min(drawStart.x, mx);
  const y = Math.min(drawStart.y, my);
  const w = Math.abs(mx - drawStart.x);
  const h = Math.abs(my - drawStart.y);
  if (drawingRect) { drawingRect.remove(); drawingRect = null; }
  if (w < 10 || h < 10) return;

  // Use DISPLAY dimensions (getBoundingClientRect), NOT canvas buffer dimensions.
  // Mouse coords are in CSS/display pixels, so percentages must use display size.
  addField(activeFieldType, currentPage, x / rect.width, y / rect.height, w / rect.width, h / rect.height);
});

canvas.addEventListener("contextmenu", (e) => e.preventDefault());

// --- Field management ---
function addField(type, page, xPct, yPct, wPct, hPct) {
  const prefix = type === "name" ? "Signature" : "Date";
  const count = fields.filter((f) => f.type === type).length + 1;

  fields.push({ id: ++fieldIdCounter, type, page, xPct, yPct, wPct, hPct, name: `${prefix}_${count}`, value: "" });
  renderFieldsOnPage();
  updateFieldList();
  updateButtons();
}

function removeField(id) {
  fields = fields.filter((f) => f.id !== id);
  renderFieldsOnPage();
  updateFieldList();
  updateButtons();
}

function updateFieldList() {
  fieldCountEl.textContent = `(${fields.length})`;
  fieldListEl.innerHTML = "";
  fields.forEach((f) => {
    const item = document.createElement("div");
    item.className = "field-list-item";
    const valueText = f.value ? ` — "${f.value}"` : "";
    item.innerHTML = `
      <span class="field-icon ${f.type}-icon">${f.type === "name" ? "N" : "D"}</span>
      <div class="field-info">
        <div class="field-label">${f.name}${valueText}</div>
        <div class="field-page">Page ${f.page}</div>
      </div>
      <button class="remove-btn" title="Remove">&times;</button>
    `;
    item.querySelector(".remove-btn").addEventListener("click", () => removeField(f.id));
    fieldListEl.appendChild(item);
  });
}

function updateButtons() {
  const hasFields = fields.length > 0;
  btnPrepare.disabled = !hasFields;
  btnSign.disabled = !hasFields;
}

// --- Mode switching ---
function updateModeUI() {
  const placingTools = document.getElementById("placing-tools");
  if (mode === "place") {
    placingTools.classList.remove("hidden");
    canvas.style.cursor = "crosshair";
    modeLabel.textContent = "Place fields on the PDF, then switch to Sign mode";
    btnSign.textContent = "Fill & Sign";
    btnPrepare.classList.remove("hidden");
  } else {
    placingTools.classList.add("hidden");
    canvas.style.cursor = "default";
    modeLabel.textContent = "Click name fields to sign. Date auto-fills.";
    btnSign.textContent = "Download Signed PDF";
    btnPrepare.classList.add("hidden");
  }
  renderFieldsOnPage();
}

btnSign.addEventListener("click", async () => {
  if (mode === "place") {
    if (fields.length === 0) return;
    mode = "sign";
    updateModeUI();
    updateFieldList();
  } else {
    downloadSignedPdf();
  }
});

async function getTimestamp() {
  try {
    const resp = await fetch("https://worldtimeapi.org/api/timezone/Etc/UTC", { signal: AbortSignal.timeout(3000) });
    if (resp.ok) {
      const data = await resp.json();
      const d = new Date(data.datetime);
      return d.toLocaleDateString("en-US", { month: "2-digit", day: "2-digit", year: "numeric" });
    }
  } catch { /* fall through */ }
  return new Date().toLocaleDateString("en-US", { month: "2-digit", day: "2-digit", year: "numeric" });
}

async function autoFillDatesOnSign() {
  // Called ONLY after a name field is signed — auto-fills all date fields
  const allNamesSigned = fields
    .filter((f) => f.type === "name")
    .every((f) => f.value);

  if (allNamesSigned) {
    const timestamp = await getTimestamp();
    fields.forEach((f) => {
      if (f.type === "date" && !f.value) {
        f.value = timestamp;
      }
    });
    renderFieldsOnPage();
    updateFieldList();
  }
}

// --- Prompt for field value (name only — date is NEVER user-editable) ---
function promptFieldValue(field) {
  if (field.type === "date") return; // date is auto-only, never editable

  const val = prompt("Type your name to sign:", field.value || "");
  if (val !== null && val.trim()) {
    field.value = val.trim();
    // Signing a name triggers date auto-fill
    autoFillDatesOnSign();
    renderFieldsOnPage();
    updateFieldList();
  }
}

// --- Prepare PDF (download with form fields for someone else to sign) ---
btnPrepare.addEventListener("click", async () => {
  if (fields.length === 0) return;
  btnPrepare.disabled = true;
  btnPrepare.textContent = "Preparing...";

  const pdfFields = fields.map((f) => ({
    name: f.name,
    page: f.page - 1,
    x_pct: f.xPct,
    y_pct: f.yPct,
    w_pct: f.wPct,
    h_pct: f.hPct,
    type: f.type,
  }));

  const formData = new FormData();
  formData.append("file", new Blob([pdfBytes], { type: "application/pdf" }), "document.pdf");
  formData.append("fields", JSON.stringify(pdfFields));

  try {
    const resp = await fetch("/api/prepare", { method: "POST", body: formData });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: "Server error" }));
      alert(`Error: ${err.detail || "Failed"}`);
      return;
    }
    downloadBlob(await resp.blob(), "prepared_document.pdf");
  } catch (err) {
    alert(`Error: ${err.message}`);
  } finally {
    btnPrepare.disabled = false;
    btnPrepare.textContent = "Prepare PDF";
  }
});

// --- Download signed (flat) PDF ---
async function downloadSignedPdf() {
  // Check all name fields have values
  const emptyNames = fields.filter((f) => f.type === "name" && !f.value);
  if (emptyNames.length > 0) {
    alert("Please fill in all signature fields before downloading.");
    return;
  }

  btnSign.disabled = true;
  btnSign.textContent = "Signing...";

  const pdfFields = fields.map((f) => ({
    name: f.name,
    page: f.page - 1,
    x_pct: f.xPct,
    y_pct: f.yPct,
    w_pct: f.wPct,
    h_pct: f.hPct,
    type: f.type,
    value: f.value || "",
  }));

  const formData = new FormData();
  formData.append("file", new Blob([pdfBytes], { type: "application/pdf" }), "document.pdf");
  formData.append("fields", JSON.stringify(pdfFields));

  try {
    const resp = await fetch("/api/sign", { method: "POST", body: formData });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: "Server error" }));
      alert(`Error: ${err.detail || "Failed"}`);
      return;
    }
    downloadBlob(await resp.blob(), "signed_document.pdf");
  } catch (err) {
    alert(`Error: ${err.message}`);
  } finally {
    btnSign.disabled = false;
    btnSign.textContent = "Download Signed PDF";
  }
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// --- Reset ---
btnReset.addEventListener("click", () => {
  pdfDoc = null;
  pdfBytes = null;
  fields = [];
  fieldIdCounter = 0;
  mode = "place";
  editorScreen.classList.add("hidden");
  uploadScreen.classList.remove("hidden");
  fileInput.value = "";
  overlay.innerHTML = "";
  fieldListEl.innerHTML = "";
  updateButtons();
});
