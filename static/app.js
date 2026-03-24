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
let fields = []; // { id, type, page, xPct, yPct, wPct, hPct, value, name }
let fieldIdCounter = 0;
let appMode = ""; // "prepare" or "sign"

// Drawing
let isDrawing = false;
let drawStart = { x: 0, y: 0 };
let drawingRect = null;

// --- DOM ---
const landingScreen = document.getElementById("landing-screen");
const editorScreen = document.getElementById("editor-screen");
const canvas = document.getElementById("pdf-canvas");
const ctx = canvas.getContext("2d");
const overlay = document.getElementById("field-overlay");
const pageInfo = document.getElementById("page-info");
const btnPrev = document.getElementById("btn-prev-page");
const btnNext = document.getElementById("btn-next-page");
const btnSign = document.getElementById("btn-sign");
const btnReset = document.getElementById("btn-reset");
const btnNameField = document.getElementById("btn-name-field");
const btnDateField = document.getElementById("btn-date-field");
const fieldListEl = document.getElementById("field-list");
const fieldCountEl = document.getElementById("field-count");
const modeLabel = document.getElementById("mode-label");
const prepareHelp = document.getElementById("prepare-help");
const signHelp = document.getElementById("sign-help");
const placingTools = document.getElementById("placing-tools");

// --- File inputs ---
document.getElementById("file-prepare").addEventListener("change", (e) => {
  if (e.target.files[0]) startPrepareMode(e.target.files[0]);
});
document.getElementById("file-sign").addEventListener("change", (e) => {
  if (e.target.files[0]) startSignMode(e.target.files[0]);
});
document.getElementById("file-lock").addEventListener("change", async (e) => {
  if (e.target.files[0]) await lockSignedPdf(e.target.files[0]);
});

// --- Lock flow: upload filled PDF → flatten + lock + download ---
async function lockSignedPdf(file) {
  const fd = new FormData();
  fd.append("file", file);
  try {
    const resp = await fetch("/api/lock-signed", { method: "POST", body: fd });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: "Server error" }));
      alert("Error: " + (err.detail || "Failed to lock PDF"));
      return;
    }
    downloadBlob(await resp.blob(), "signed_locked.pdf");
  } catch (err) {
    alert("Error: " + err.message);
  }
}

// --- Prepare mode: place fields ---
async function startPrepareMode(file) {
  appMode = "prepare";
  await loadPdf(file);
  placingTools.classList.remove("hidden");
  canvas.style.cursor = "crosshair";
  modeLabel.textContent = "Place fields, then click Send for Signing";
  btnSign.textContent = "Send for Signing";
  btnSign.disabled = true;
  prepareHelp.classList.remove("hidden");
  signHelp.classList.add("hidden");
}

// --- Sign mode: detect fields from prepared PDF, let user sign ---
async function startSignMode(file) {
  appMode = "sign";
  await loadPdf(file);

  // Detect AcroForm fields from the prepared PDF via backend
  const formData = new FormData();
  formData.append("file", new Blob([pdfBytes], { type: "application/pdf" }), "doc.pdf");

  try {
    const resp = await fetch("/api/detect-fields", { method: "POST", body: formData });
    if (resp.ok) {
      const detected = await resp.json();
      if (detected.fields && detected.fields.length > 0) {
        fields = detected.fields.map((f, i) => ({
          id: ++fieldIdCounter,
          type: f.type,
          page: f.page + 1, // 1-based for frontend
          xPct: f.x_pct,
          yPct: f.y_pct,
          wPct: f.w_pct,
          hPct: f.h_pct,
          name: f.name,
          value: "",
        }));
      } else {
        alert("This PDF has no signature fields. Please use 'Prepare Document' first.");
        resetApp();
        return;
      }
    }
  } catch (err) {
    alert("Could not detect fields: " + err.message);
    resetApp();
    return;
  }

  placingTools.classList.add("hidden");
  canvas.style.cursor = "default";
  modeLabel.textContent = "Click name fields to sign. Date auto-fills.";
  btnSign.textContent = "Download Signed PDF";
  btnSign.disabled = true;
  prepareHelp.classList.add("hidden");
  signHelp.classList.remove("hidden");
  renderFieldsOnPage();
  updateFieldList();
}

// --- Load PDF ---
async function loadPdf(file) {
  const arrayBuf = await file.arrayBuffer();
  pdfBytes = new Uint8Array(arrayBuf);
  pdfDoc = await pdfjsLib.getDocument({ data: pdfBytes.slice() }).promise;
  totalPages = pdfDoc.numPages;
  currentPage = 1;
  fields = [];
  fieldIdCounter = 0;
  landingScreen.classList.add("hidden");
  editorScreen.classList.remove("hidden");
  await renderPage(currentPage);
  updatePageControls();
  updateFieldList();
}

// --- Rendering ---
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
  const displayRect = canvas.getBoundingClientRect();
  const dw = displayRect.width;
  const dh = displayRect.height;

  fields.filter((f) => f.page === currentPage).forEach((f) => {
    const sx = f.xPct * dw, sy = f.yPct * dh, sw = f.wPct * dw, sh = f.hPct * dh;

    const el = document.createElement("div");
    el.className = `placed-field ${f.type}-field`;
    el.style.left = sx + "px";
    el.style.top = sy + "px";
    el.style.width = sw + "px";
    el.style.height = sh + "px";

    if (appMode === "sign") {
      // Sign mode rendering
      if (f.type === "date") {
        el.classList.add("locked");
        el.style.cursor = "not-allowed";
        el.textContent = f.value || "Auto-fills when signed";
        el.style.fontSize = f.value ? Math.min(sh * 0.6, 14) + "px" : "9px";
        if (f.value) el.classList.add("filled");
        else el.style.opacity = "0.5";
      } else {
        el.style.cursor = "pointer";
        if (f.value) {
          el.textContent = f.value;
          el.style.fontSize = Math.min(sh * 0.6, 16) + "px";
          el.classList.add("filled");
        } else {
          el.textContent = "Click to sign";
          el.style.fontSize = "11px";
          el.style.opacity = "0.7";
        }
        el.addEventListener("click", (e) => { e.stopPropagation(); promptSign(f); });
      }
    } else {
      // Prepare mode rendering
      el.textContent = f.type === "name" ? "Name" : "Date";
      const del = document.createElement("button");
      del.className = "delete-btn";
      del.textContent = "\u00d7";
      del.addEventListener("click", (e) => { e.stopPropagation(); removeField(f.id); });
      el.appendChild(del);
    }

    overlay.appendChild(el);
  });
}

// --- Page nav ---
document.getElementById("canvas-container").addEventListener("scroll", syncOverlay);
window.addEventListener("resize", () => { syncOverlay(); renderFieldsOnPage(); });

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

// --- Tool selection (prepare mode) ---
btnNameField.addEventListener("click", () => setActiveFieldType("name"));
btnDateField.addEventListener("click", () => setActiveFieldType("date"));
function setActiveFieldType(type) {
  activeFieldType = type;
  btnNameField.classList.toggle("active", type === "name");
  btnDateField.classList.toggle("active", type === "date");
}

// --- Drawing (prepare mode) ---
canvas.addEventListener("mousedown", (e) => {
  if (appMode !== "prepare") return;
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
  const mx = e.clientX - rect.left, my = e.clientY - rect.top;
  drawingRect.style.left = Math.min(drawStart.x, mx) + "px";
  drawingRect.style.top = Math.min(drawStart.y, my) + "px";
  drawingRect.style.width = Math.abs(mx - drawStart.x) + "px";
  drawingRect.style.height = Math.abs(my - drawStart.y) + "px";
});
canvas.addEventListener("mouseup", (e) => {
  if (!isDrawing) return;
  isDrawing = false;
  const rect = canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left, my = e.clientY - rect.top;
  const x = Math.min(drawStart.x, mx), y = Math.min(drawStart.y, my);
  const w = Math.abs(mx - drawStart.x), h = Math.abs(my - drawStart.y);
  if (drawingRect) { drawingRect.remove(); drawingRect = null; }
  if (w < 10 || h < 10) return;
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
  btnSign.disabled = fields.length === 0;
}

function removeField(id) {
  fields = fields.filter((f) => f.id !== id);
  renderFieldsOnPage();
  updateFieldList();
  btnSign.disabled = fields.length === 0;
}

function updateFieldList() {
  fieldCountEl.textContent = `(${fields.length})`;
  fieldListEl.innerHTML = "";
  fields.forEach((f) => {
    const val = f.value ? ` \u2014 "${f.value}"` : "";
    const item = document.createElement("div");
    item.className = "field-list-item";
    item.innerHTML = `
      <span class="field-icon ${f.type}-icon">${f.type === "name" ? "N" : "D"}</span>
      <div class="field-info">
        <div class="field-label">${f.name}${val}</div>
        <div class="field-page">Page ${f.page}</div>
      </div>
      ${appMode === "prepare" ? '<button class="remove-btn" title="Remove">&times;</button>' : ""}
    `;
    if (appMode === "prepare") {
      item.querySelector(".remove-btn").addEventListener("click", () => removeField(f.id));
    }
    fieldListEl.appendChild(item);
  });
}

// --- Sign: prompt for name (date is NEVER editable) ---
function promptSign(field) {
  if (field.type === "date") return;
  const val = prompt("Type your name to sign:", field.value || "");
  if (val !== null && val.trim()) {
    field.value = val.trim();
    autoFillDates();
    renderFieldsOnPage();
    updateFieldList();
    checkSignReady();
  }
}

async function autoFillDates() {
  const allSigned = fields.filter((f) => f.type === "name").every((f) => f.value);
  if (!allSigned) return;
  const ts = await getTimestamp();
  fields.forEach((f) => { if (f.type === "date" && !f.value) f.value = ts; });
}

async function getTimestamp() {
  try {
    const r = await fetch("https://worldtimeapi.org/api/timezone/Etc/UTC", { signal: AbortSignal.timeout(3000) });
    if (r.ok) { const d = await r.json(); return new Date(d.datetime).toLocaleDateString("en-US"); }
  } catch {}
  return new Date().toLocaleDateString("en-US");
}

function checkSignReady() {
  const namesFilled = fields.filter((f) => f.type === "name").every((f) => f.value);
  btnSign.disabled = !namesFilled;
}

// --- Main action button ---
btnSign.addEventListener("click", async () => {
  if (appMode === "prepare") {
    await downloadPreparedPdf();
  } else {
    await downloadSignedPdf();
  }
});

// --- Prepare: download PDF with AcroForm fields ---
async function downloadPreparedPdf() {
  btnSign.disabled = true;
  btnSign.textContent = "Preparing...";
  const pdfFields = fields.map((f) => ({
    name: f.name, page: f.page - 1, x_pct: f.xPct, y_pct: f.yPct,
    w_pct: f.wPct, h_pct: f.hPct, type: f.type,
  }));
  const fd = new FormData();
  fd.append("file", new Blob([pdfBytes], { type: "application/pdf" }), "doc.pdf");
  fd.append("fields", JSON.stringify(pdfFields));
  try {
    const resp = await fetch("/api/prepare", { method: "POST", body: fd });
    if (!resp.ok) { alert("Error preparing PDF"); return; }
    downloadBlob(await resp.blob(), "prepared_for_signing.pdf");
  } catch (err) { alert(err.message); }
  finally { btnSign.disabled = false; btnSign.textContent = "Send for Signing"; }
}

// --- Sign: download flat locked PDF ---
async function downloadSignedPdf() {
  const empty = fields.filter((f) => f.type === "name" && !f.value);
  if (empty.length) { alert("Please sign all name fields."); return; }
  btnSign.disabled = true;
  btnSign.textContent = "Signing...";
  const pdfFields = fields.map((f) => ({
    name: f.name, page: f.page - 1, x_pct: f.xPct, y_pct: f.yPct,
    w_pct: f.wPct, h_pct: f.hPct, type: f.type, value: f.value || "",
  }));
  const fd = new FormData();
  fd.append("file", new Blob([pdfBytes], { type: "application/pdf" }), "doc.pdf");
  fd.append("fields", JSON.stringify(pdfFields));
  try {
    const resp = await fetch("/api/sign", { method: "POST", body: fd });
    if (!resp.ok) { alert("Error signing PDF"); return; }
    downloadBlob(await resp.blob(), "signed_document.pdf");
  } catch (err) { alert(err.message); }
  finally { btnSign.disabled = false; btnSign.textContent = "Download Signed PDF"; }
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click();
  document.body.removeChild(a); URL.revokeObjectURL(url);
}

// --- Reset ---
btnReset.addEventListener("click", resetApp);
function resetApp() {
  pdfDoc = null; pdfBytes = null; fields = []; fieldIdCounter = 0; appMode = "";
  editorScreen.classList.add("hidden");
  landingScreen.classList.remove("hidden");
  document.getElementById("file-prepare").value = "";
  document.getElementById("file-sign").value = "";
  overlay.innerHTML = "";
}
