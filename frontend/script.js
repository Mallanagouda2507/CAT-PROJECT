const state = {
  documents: [],
  analytics: null,
  activeDocument: null,
  selectedFile: null,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const icon = (name) => `<i data-lucide="${name}"></i>`;
const safe = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[character]));

function refreshIcons() {
  if (window.lucide) window.lucide.createIcons();
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.error || `Request failed (${response.status}).`);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

function showToast(message, type = "") {
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  $("#toast-container").append(toast);
  window.setTimeout(() => toast.remove(), 3600);
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(date);
}

function formatBytes(bytes) {
  if (!bytes) return "—";
  return bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function documentIcon(mimeType) {
  if (mimeType === "application/pdf") return "file-text";
  if (mimeType && mimeType.startsWith("image/")) return "image";
  return "file";
}

function statusMarkup(status) {
  const label = status === "succeeded" ? "Succeeded" : status === "processing" ? "Processing" : "Failed";
  return `<span class="status-pill status-${safe(status)}">${label}</span>`;
}

function documentRow(document, includeSize = false) {
  const iconClass = document.mime_type === "application/pdf" ? "pdf" : "image";
  return `<tr>
    <td><div class="doc-cell"><span class="file-icon ${iconClass}">${icon(documentIcon(document.mime_type))}</span><div><div class="doc-name" title="${safe(document.original_name)}">${safe(document.original_name)}</div><div class="doc-subtitle">${safe(formatBytes(document.file_size))} · ${safe(document.document_type || "Document")}</div></div></div></td>
    <td>${safe(document.document_type || "Document")}</td>
    <td>${safe(formatDate(document.uploaded_at))}</td>
    ${includeSize ? `<td>${safe(formatBytes(document.file_size))}</td>` : ""}
    <td>${statusMarkup(document.status)}</td>
    <td><div class="row-actions"><button class="row-action" data-view-document="${safe(document.id)}" title="View results" aria-label="View results">${icon("eye")}</button><button class="row-action delete" data-delete-document="${safe(document.id)}" title="Delete document" aria-label="Delete document">${icon("trash-2")}</button></div></td>
  </tr>`;
}

function renderDocuments() {
  const recent = state.documents.slice(0, 5);
  $("#recent-table").innerHTML = recent.map((document) => documentRow(document)).join("");
  $("#history-table").innerHTML = filterDocuments().map((document) => documentRow(document, true)).join("");
  $("#analytics-recent").innerHTML = recent.map((document) => documentRow(document)).join("");
  $("#nav-count").textContent = state.documents.length;
  $("#history-count").textContent = state.documents.length;
  $("#recent-empty").classList.toggle("hidden", state.documents.length > 0);
  $("#history-empty").classList.toggle("hidden", filterDocuments().length > 0);
  $("#analytics-empty").classList.toggle("hidden", state.documents.length > 0);
  refreshIcons();
}

function filterDocuments() {
  const query = ($("#history-search")?.value || "").trim().toLowerCase();
  return state.documents.filter((document) => document.original_name.toLowerCase().includes(query));
}

function renderStats(data) {
  $("#stat-total").textContent = data.total;
  $("#stat-success").textContent = data.succeeded;
  $("#stat-rate").innerHTML = `${data.success_rate}<small>%</small>`;
  $("#stat-failed").textContent = data.failed;
  $("#analytics-total").textContent = data.total;
  $("#analytics-success").textContent = data.succeeded;
  $("#analytics-failed").textContent = data.failed;
  $("#analytics-rate").innerHTML = `${data.success_rate}<small>%</small>`;
  renderTypeBreakdown(data.by_type || []);
  drawActivityChart($("#activity-chart"), data.daily || [], $("#chart-empty"));
  drawActivityChart($("#analytics-chart"), data.daily || [], $("#analytics-chart-empty"));
}

function renderTypeBreakdown(rows) {
  const root = $("#type-breakdown");
  if (!rows.length) {
    root.innerHTML = '<div class="no-data">Document type statistics will appear here.</div>';
    return;
  }
  const max = Math.max(...rows.map((row) => row.count));
  root.innerHTML = rows.map((row) => `<div><div class="type-row-head"><span>${safe(row.type)}</span><strong>${row.count}</strong></div><div class="bar-track"><div class="bar-fill" style="width:${Math.max(5, row.count / max * 100)}%"></div></div></div>`).join("");
}

function drawActivityChart(canvas, rows, empty) {
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(100, rect.width);
  const height = Math.max(100, rect.height);
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);
  context.clearRect(0, 0, width, height);
  const dateMap = new Map(rows.map((row) => [row.date, row.count]));
  const dates = Array.from({ length: 7 }, (_, index) => {
    const date = new Date();
    date.setDate(date.getDate() - (6 - index));
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
    return { key, label: new Intl.DateTimeFormat(undefined, { weekday: "short" }).format(date), count: dateMap.get(key) || 0 };
  });
  const hasData = dates.some((item) => item.count > 0);
  empty.classList.toggle("hidden", hasData);
  if (!hasData) return;
  const pad = { top: 14, right: 12, bottom: 27, left: 26 };
  const chartWidth = width - pad.left - pad.right;
  const chartHeight = height - pad.top - pad.bottom;
  const maximum = Math.max(4, ...dates.map((item) => item.count));
  context.font = "9px DM Sans, sans-serif";
  context.textAlign = "right";
  context.textBaseline = "middle";
  for (let tick = 0; tick <= 3; tick += 1) {
    const y = pad.top + chartHeight - (chartHeight * tick / 3);
    context.strokeStyle = "#edf0f5";
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(pad.left, y);
    context.lineTo(width - pad.right, y);
    context.stroke();
    context.fillStyle = "#a3adbc";
    context.fillText(String(Math.round(maximum * tick / 3)), pad.left - 7, y);
  }
  const step = chartWidth / dates.length;
  const barWidth = Math.min(24, step * .42);
  dates.forEach((item, index) => {
    const x = pad.left + step * index + (step - barWidth) / 2;
    const barHeight = item.count ? Math.max(3, chartHeight * item.count / maximum) : 0;
    const y = pad.top + chartHeight - barHeight;
    context.fillStyle = item.count ? "#718ee8" : "#eef1f7";
    context.beginPath();
    context.roundRect(x, y, barWidth, Math.max(2, barHeight), 4);
    context.fill();
    context.fillStyle = "#99a4b4";
    context.textAlign = "center";
    context.textBaseline = "top";
    context.fillText(item.label, x + barWidth / 2, height - 18);
  });
}

async function refreshDashboard() {
  try {
    const [documentsPayload, analytics, status] = await Promise.all([
      api("/api/documents"),
      api("/api/analytics"),
      api("/api/status"),
    ]);
    state.documents = documentsPayload.documents;
    state.analytics = analytics;
    renderDocuments();
    renderStats(analytics);
    const configured = status.document_ai_configured;
    $("#cloud-warning").classList.toggle("hidden", configured);
    $("#sidebar-cloud-state").textContent = configured ? "Processor configured" : "Setup required";
    $("#sidebar-cloud-copy").textContent = configured
      ? "Your Google Cloud processor is ready."
      : "Set up your Google Cloud processor to enable live extraction.";
    $(".cloud-mini").classList.toggle("is-connected", configured);
    $(".cloud-mini").classList.toggle("is-disconnected", !configured);
    $("#integration-status").classList.toggle("is-connected", configured);
    $("#integration-status").classList.toggle("is-disconnected", !configured);
    $("#integration-status span:last-child").textContent = configured ? "Processor configured" : "Configuration required";
    refreshIcons();
  } catch (error) {
    showToast(error.message, "error");
  }
}

function navigate(view) {
  const titles = { dashboard: "Overview", documents: "Documents", analytics: "Analytics", integration: "Cloud AI integration" };
  $$(".view").forEach((section) => section.classList.toggle("active", section.id === `view-${view}`));
  $$(".nav-item[data-view]").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  $("#breadcrumb-current").textContent = titles[view] || "Overview";
  $("#sidebar").classList.remove("open");
  if (view === "analytics") window.setTimeout(() => state.analytics && renderStats(state.analytics), 30);
}

function openUpload() {
  resetUpload();
  $("#upload-modal").classList.remove("hidden");
  $("#browse-files").focus();
}

function closeUpload() {
  if (!$("#process-button").disabled || $("#upload-progress").classList.contains("hidden")) {
    $("#upload-modal").classList.add("hidden");
    resetUpload();
  }
}

function resetUpload() {
  const previewUrl = $("#file-preview").dataset.url;
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  $("#file-preview").innerHTML = "";
  $("#file-preview").dataset.url = "";
  $("#file-preview").classList.add("hidden");
  state.selectedFile = null;
  $("#file-input").value = "";
  $("#selected-file").classList.add("hidden");
  $("#upload-error").classList.add("hidden");
  $("#upload-progress").classList.add("hidden");
  $("#progress-bar").style.width = "0%";
  $("#progress-label").textContent = "Uploading and processing...";
  $("#progress-percent").textContent = "0%";
  $("#progress-detail").textContent = "Waiting for OCR.space response";
  $("#process-button").disabled = true;
  $("#process-button").innerHTML = `${icon("sparkles")} Process with AI`;
  $("#dropzone").classList.remove("hidden");
  refreshIcons();
}

function setSelectedFile(file) {
  const extension = file.name.split(".").pop().toLowerCase();
  const acceptedExtensions = ["pdf", "png", "jpg", "jpeg"];
  const acceptedMimes = ["application/pdf", "image/png", "image/jpeg", "application/octet-stream"];
  let error = "";
  if (!acceptedExtensions.includes(extension)) error = "Unsupported file type. Please choose a PDF, PNG, or JPG.";
  else if (file.size === 0) error = "This file is empty. Choose a document with content.";
  else if (file.size > 15 * 1024 * 1024) error = "The selected file exceeds the 15 MB upload limit.";
  else if (file.type && !acceptedMimes.includes(file.type)) error = "The browser reports an unsupported file MIME type.";
  if (error) {
    state.selectedFile = null;
    $("#process-button").disabled = true;
    $("#upload-error").textContent = error;
    $("#upload-error").classList.remove("hidden");
    $("#selected-file").classList.add("hidden");
    return;
  }
  state.selectedFile = file;
  $("#upload-error").classList.add("hidden");
  $("#dropzone").classList.add("hidden");
  $("#selected-file").innerHTML = `${icon(documentIcon(file.type))}<strong title="${safe(file.name)}">${safe(file.name)}</strong><span>${safe(formatBytes(file.size))}</span><button class="row-action" id="remove-selected" title="Remove file" aria-label="Remove file">${icon("x")}</button>`;
  $("#selected-file").classList.remove("hidden");
  const previewUrl = URL.createObjectURL(file);
  $("#file-preview").dataset.url = previewUrl;
  $("#file-preview").innerHTML = extension === "pdf"
    ? `<iframe title="PDF preview" src="${previewUrl}"></iframe>`
    : `<img alt="Selected document preview" src="${previewUrl}">`;
  $("#file-preview").classList.remove("hidden");
  $("#process-button").disabled = false;
  refreshIcons();
}

function uploadSelectedFile() {
  if (!state.selectedFile) return;
  const data = new FormData();
  data.append("document", state.selectedFile);
  data.append("provider", "ocr_space");
  const documentId = crypto.randomUUID();
  data.append("document_id", documentId);
  $("#process-button").disabled = true;
  $("#dropzone").classList.add("hidden");
  $("#upload-progress").classList.remove("hidden");
  $("#upload-error").classList.add("hidden");
  $("#progress-label").textContent = "Uploading and processing...";
  $("#progress-percent").textContent = "0%";
  $("#progress-bar").style.width = "0%";
  $("#progress-detail").textContent = "Waiting for OCR.space response";
  let polling = true;
  const progressPoll = pollUploadProgress(documentId, () => polling);
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/upload");
  xhr.upload.addEventListener("progress", (event) => {
    if (!event.lengthComputable) return;
    const percentage = Math.min(100, Math.round(event.loaded / event.total * 100));
    $("#progress-percent").textContent = `${percentage}%`;
    $("#progress-bar").style.width = `${percentage}%`;
    if (percentage === 100) {
      $("#progress-label").textContent = "Document uploaded · Preparing OCR...";
      $("#progress-detail").textContent = "Reading PDF pages and preparing OCR requests";
    }
  });
  xhr.addEventListener("load", async () => {
    polling = false;
    await progressPoll;
    let response;
    try { response = JSON.parse(xhr.responseText); } catch { response = {}; }
    if (xhr.status >= 200 && xhr.status < 300 && response.status === "succeeded") {
      $("#progress-bar").style.width = "100%";
      $("#progress-percent").textContent = "Complete";
      $("#progress-label").textContent = "Extraction complete";
      $("#progress-detail").textContent = "All document pages were processed";
      $("#upload-modal").classList.add("hidden");
      resetUpload();
      await refreshDashboard();
      showToast("Document processed successfully by OCR.space.", "success");
      if (response.id) openDocument(response.id);
      return;
    }
    const message = response.error || "The document could not be processed.";
    $("#progress-label").textContent = "Processing could not be completed";
    $("#progress-detail").textContent = "Review the processing result for page and chunk status";
    $("#upload-error").textContent = message;
    $("#upload-error").classList.remove("hidden");
    $("#process-button").disabled = false;
    await refreshDashboard();
    showToast(message, "error");
    if (response.id && response.result) {
      $("#upload-modal").classList.add("hidden");
      resetUpload();
      openDocument(response.id);
    }
  });
  xhr.addEventListener("error", () => {
    polling = false;
    $("#upload-error").textContent = "Could not reach the application server. Check your connection and try again.";
    $("#upload-error").classList.remove("hidden");
    $("#process-button").disabled = false;
  });
  xhr.send(data);
}

async function pollUploadProgress(documentId, isActive) {
  while (isActive()) {
    try {
      const payload = await api(`/api/documents/${encodeURIComponent(documentId)}`);
      const document = payload.document;
      const progress = document.progress;
      if (progress?.total_pages) {
        const total = progress.total_pages;
        const completed = Math.min(progress.completed_pages || 0, total);
        const percent = Math.floor(completed / total * 100);
        $("#progress-bar").style.width = `${percent}%`;
        $("#progress-percent").textContent = `${completed} / ${total} pages`;
        $("#progress-label").textContent = document.status === "processing"
          ? `Processing pages ${completed} of ${total}`
          : document.status === "succeeded" ? "Extraction complete" : "Processing could not be completed";
        $("#progress-detail").textContent = progress.total_chunks
          ? `Chunks ${progress.completed_chunks} of ${progress.total_chunks} complete`
          : "Preparing OCR chunks";
      }
      if (document.status !== "processing") break;
    } catch (error) {
      if (error.status !== 404) {
        $("#progress-detail").textContent = "Progress is temporarily unavailable; processing continues.";
      }
    }
    await new Promise((resolve) => window.setTimeout(resolve, 600));
  }
}

function displayValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") {
    if ("amount" in value) return `${value.currency || ""} ${Number(value.amount).toLocaleString(undefined, { maximumFractionDigits: 2 })}`.trim();
    if ("year" in value && "month" in value && "day" in value) return `${value.year}-${String(value.month).padStart(2, "0")}-${String(value.day).padStart(2, "0")}`;
    return Object.entries(value).map(([key, child]) => `${key.replaceAll("_", " ")}: ${displayValue(child)}`).join(", ");
  }
  return String(value);
}

function labelFor(key) {
  const labels = {
    supplier_name: "Supplier", supplier_address: "Supplier address",
    supplier_tax_id: "Supplier tax ID", receiver_name: "Customer",
    receiver_address: "Customer address", invoice_id: "Invoice number",
    invoice_date: "Invoice date", due_date: "Due date",
    net_amount: "Subtotal", total_tax_amount: "Tax amount",
    total_amount: "Total amount", currency: "Currency",
    purchase_order: "Purchase order", payment_terms: "Payment terms",
  };
  return labels[key] || key.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function renderFields(fields) {
  const entries = Object.entries(fields || {});
  if (!entries.length) return '<div class="no-data">No structured invoice fields were returned for this document.</div>';
  return `<div class="result-fields">${entries.map(([key, entity]) => `<div class="result-field"><div class="field-name">${safe(labelFor(key))}</div><div class="field-value">${safe(displayValue(entity.value))}<span class="confidence">${Math.round((entity.confidence || 0) * 100)}% confidence</span></div></div>`).join("")}</div>`;
}

function renderOcrSummary(result) {
  const pages = result.pages || [];
  const chunks = result.chunks || [];
  const succeededPages = pages.filter((page) => page.status === "succeeded").length;
  const failedPages = pages.filter((page) => page.status === "failed").length;
  const pendingPages = pages.filter((page) => page.status === "not_attempted").length;
  const pageRows = pages.map((page) => {
    const detail = page.error ? ` · ${page.error}` : "";
    return `<div class="doc-subtitle">Page ${page.page} · ${safe(page.status)}${safe(detail)}</div>`;
  }).join("");
  const chunkRows = chunks.map((chunk) => {
    const label = `Chunk ${chunk.index} · pages ${chunk.start_page}–${chunk.end_page}`;
    const detail = chunk.error ? ` · ${chunk.error}` : "";
    return `<div class="doc-subtitle">${safe(label)} · ${safe(chunk.status)}${safe(detail)}</div>`;
  }).join("");
  return `<section class="result-section"><h3>${icon("files")} Page and chunk results</h3>
    <div class="no-data">${succeededPages} of ${result.page_count} pages extracted · ${failedPages} failed · ${pendingPages} not attempted</div>
    <div class="doc-subtitle">${result.successful_chunks?.length || 0} successful chunks · ${result.failed_chunks?.length || 0} failed chunks · ${result.unprocessed_chunks?.length || 0} not attempted</div>
    ${pageRows}
    ${chunkRows}
    <div class="doc-subtitle">OCR.space returns recognized text only; structured invoice fields are not provided.</div>
  </section>`;
}

function renderResult(document) {
  const result = document.result;
  const succeeded = document.status === "succeeded" && result;
  const hasResult = Boolean(result);
  const metaStatus = statusMarkup(document.status);
  $("#results-title").textContent = document.original_name;
  const textOnly = hasResult && result.provider === "ocr_space";
  const defaultTab = succeeded && textOnly ? "text" : "summary";
  const progress = document.progress;
  const pageCount = result?.page_count || progress?.total_pages;
  const chunkCount = result?.chunks?.length;
  $("#result-meta").innerHTML = `${metaStatus}<span>${safe(document.document_type || "Document")}</span><span>${safe(formatDate(document.uploaded_at))}</span>${pageCount ? `<span>${safe(pageCount)} page${pageCount === 1 ? "" : "s"}</span>` : ""}${chunkCount ? `<span>${safe(result.successful_chunks?.length || 0)} / ${safe(chunkCount)} chunks succeeded</span>` : ""}`;
  $("#result-error").classList.toggle("hidden", !document.error_message);
  $("#result-error").textContent = document.error_message || "";
  $("#result-summary").classList.toggle("hidden", !hasResult || defaultTab === "text");
  $("#result-text").classList.toggle("hidden", !hasResult || defaultTab !== "text");
  $$(".result-tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.resultTab === defaultTab));
  if (hasResult) {
    $("#result-summary").innerHTML = textOnly ? renderOcrSummary(result) : "";
    const fields = result.fields || {};
    const supplier = Object.fromEntries(Object.entries(fields).filter(([key]) => /supplier|receiver|customer|address|tax_id/.test(key)));
    const financial = Object.fromEntries(Object.entries(fields).filter(([key]) => /amount|tax|currency|total|subtotal|net/.test(key)));
    const other = Object.fromEntries(Object.entries(fields).filter(([key]) => !(key in supplier) && !(key in financial)));
    const lineItems = result.line_items || [];
    $("#result-summary").innerHTML = textOnly
      ? renderOcrSummary(result)
      : `<section class="result-section"><h3>${icon("building-2")} Supplier & customer</h3>${renderFields(supplier)}</section>
      <section class="result-section"><h3>${icon("receipt-text")} Invoice details</h3>${renderFields(other)}</section>
      <section class="result-section"><h3>${icon("banknote")} Financial details</h3>${renderFields(financial)}</section>
      <section class="result-section"><h3>${icon("list") } Line items <span class="confidence">${lineItems.length} found</span></h3>${lineItems.length ? lineItems.map((item, index) => `<div class="line-item"><div class="line-item-name">Line item ${index + 1}</div><div class="line-item-props">${Object.entries(item.properties || {}).map(([key, property]) => `<span><b>${safe(labelFor(key))}:</b> ${safe(displayValue(property.value))} <small>(${Math.round((property.confidence || 0) * 100)}%)</small></span>`).join("") || safe(displayValue(item.value))}</div></div>`).join("") : '<div class="no-data">No line items were returned by the processor.</div>'}</section>
      <div class="doc-subtitle">${safe(result.processor || "Google Cloud Document AI Invoice Parser")}${textOnly ? "" : " · Confidence values are provided by the processor."}</div>`;
    $("#result-text").textContent = result.text || "No full text was returned.";
  } else {
    $("#result-summary").innerHTML = "";
    $("#result-text").textContent = "";
  }
  refreshIcons();
  $("#results-modal").classList.remove("hidden");
}

async function openDocument(id) {
  try {
    const payload = await api(`/api/documents/${encodeURIComponent(id)}`);
    state.activeDocument = payload.document;
    renderResult(payload.document);
  } catch (error) {
    showToast(error.message, "error");
  }
}

function downloadFile(filename, content, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function flattenForCsv(document) {
  const result = document.result || {};
  const rows = [["Field", "Value", "Confidence"]];
  for (const [key, entity] of Object.entries(result.fields || {})) {
    rows.push([labelFor(key), displayValue(entity.value), `${Math.round((entity.confidence || 0) * 100)}%`]);
  }
  for (const [index, item] of (result.line_items || []).entries()) {
    for (const [key, entity] of Object.entries(item.properties || {})) {
      rows.push([`Line item ${index + 1} - ${labelFor(key)}`, displayValue(entity.value), `${Math.round((entity.confidence || 0) * 100)}%`]);
    }
  }
  return rows.map((row) => row.map((value) => `"${String(value ?? "").replaceAll('"', '""')}"`).join(",")).join("\r\n");
}

function closeResults() {
  $("#results-modal").classList.add("hidden");
  state.activeDocument = null;
}

async function deleteDocument(id) {
  const document = state.documents.find((item) => item.id === id);
  if (!document || !window.confirm(`Delete "${document.original_name}" and its local file? This cannot be undone.`)) return;
  try {
    await api(`/api/documents/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (state.activeDocument?.id === id) closeResults();
    showToast("Document and local file deleted.", "success");
    await refreshDashboard();
  } catch (error) {
    showToast(error.message, "error");
  }
}

document.addEventListener("click", (event) => {
  const nav = event.target.closest("[data-view]");
  if (nav) navigate(nav.dataset.view);
  const directNav = event.target.closest("[data-navigate]");
  if (directNav) navigate(directNav.dataset.navigate);
  if (event.target.closest("[data-open-upload]")) openUpload();
  const viewButton = event.target.closest("[data-view-document]");
  if (viewButton) openDocument(viewButton.dataset.viewDocument);
  const deleteButton = event.target.closest("[data-delete-document]");
  if (deleteButton) deleteDocument(deleteButton.dataset.deleteDocument);
  if (event.target.closest(".close-modal")) closeUpload();
  if (event.target.closest(".close-results")) closeResults();
  if (event.target.closest("#remove-selected")) {
    const previewUrl = $("#file-preview").dataset.url;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    $("#file-preview").innerHTML = "";
    $("#file-preview").dataset.url = "";
    $("#file-preview").classList.add("hidden");
    state.selectedFile = null;
    $("#selected-file").classList.add("hidden");
    $("#dropzone").classList.remove("hidden");
    $("#process-button").disabled = true;
  }
});

$("#mobile-menu").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
$("#refresh-button").addEventListener("click", refreshDashboard);
$("#analytics-refresh").addEventListener("click", refreshDashboard);
$("#history-search").addEventListener("input", renderDocuments);
$("#browse-files").addEventListener("click", () => $("#file-input").click());
$("#dropzone").addEventListener("click", (event) => {
  if (event.target.closest("#browse-files")) return;
  $("#file-input").click();
});
$("#dropzone").addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") $("#file-input").click();
});
$("#file-input").addEventListener("change", (event) => {
  if (event.target.files?.[0]) setSelectedFile(event.target.files[0]);
});
$("#process-button").addEventListener("click", uploadSelectedFile);
$("#dropzone").addEventListener("dragover", (event) => {
  event.preventDefault();
  $("#dropzone").classList.add("drag-over");
});
$("#dropzone").addEventListener("dragleave", () => $("#dropzone").classList.remove("drag-over"));
$("#dropzone").addEventListener("drop", (event) => {
  event.preventDefault();
  $("#dropzone").classList.remove("drag-over");
  if (event.dataTransfer.files?.[0]) setSelectedFile(event.dataTransfer.files[0]);
});
$$(".result-tab").forEach((tab) => tab.addEventListener("click", () => {
  const showText = tab.dataset.resultTab === "text";
  $$(".result-tab").forEach((item) => item.classList.toggle("active", item === tab));
  $("#result-summary").classList.toggle("hidden", showText || !state.activeDocument?.result);
  $("#result-text").classList.toggle("hidden", !showText || !state.activeDocument?.result);
  $("#result-error").classList.toggle("hidden", !state.activeDocument?.error_message);
}));
$("#copy-text").addEventListener("click", async () => {
  const text = state.activeDocument?.result?.text;
  if (!text) return showToast("There is no extracted text to copy.", "error");
  try {
    await navigator.clipboard.writeText(text);
    showToast("Extracted text copied to clipboard.", "success");
  } catch {
    showToast("Clipboard access is unavailable in this browser.", "error");
  }
});
$("#download-json").addEventListener("click", () => {
  if (!state.activeDocument?.result) return showToast("No successful extraction is available to download.", "error");
  downloadFile(`${state.activeDocument.original_name}.json`, JSON.stringify({
    document: state.activeDocument.original_name,
    status: state.activeDocument.status,
    uploaded_at: state.activeDocument.uploaded_at,
    ...state.activeDocument.result,
  }, null, 2), "application/json");
});
  $("#download-text").addEventListener("click", () => {
    const text = state.activeDocument?.result?.text;
    if (!text) return showToast("There is no extracted text to download.", "error");
    downloadFile(`${state.activeDocument.original_name}.txt`, text, "text/plain;charset=utf-8");
  });
$("#download-csv").addEventListener("click", () => {
  if (!state.activeDocument?.result) return showToast("No successful extraction is available to download.", "error");
  downloadFile(`${state.activeDocument.original_name}.csv`, flattenForCsv(state.activeDocument), "text/csv;charset=utf-8");
});
$("#upload-modal").addEventListener("click", (event) => {
  if (event.target === $("#upload-modal")) closeUpload();
});
$("#results-modal").addEventListener("click", (event) => {
  if (event.target === $("#results-modal")) closeResults();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeUpload();
    closeResults();
    $("#sidebar").classList.remove("open");
  }
});

$("#current-date").textContent = new Intl.DateTimeFormat(undefined, { weekday: "short", month: "short", day: "numeric" }).format(new Date());
refreshIcons();
refreshDashboard();
window.addEventListener("resize", () => {
  if (state.analytics) renderStats(state.analytics);
});
