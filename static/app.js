const state = {
  fields: [],
  rows: [],
  rateCard: [],
  rateCards: [],
  selectedShape: "e6-standard-ax",
  pricing: null,
};

const PREVIEW_FIELD_RULES = [
  { label: "Application Name", contains: ["application name"] },
  { label: "Environment", contains: ["environment"] },
  { label: "Application Details", containsAny: [["application details"], ["application type"], ["description"]] },
  { label: "Application Version", contains: ["application version"], section: "Application Details" },
  { label: "Operating System", containsAny: [["operating system"], ["os version"], [" os "]], section: "Application Details" },
  { label: "CPUs", containsAny: [["number of cpu cores per server"], ["number of cpus"], ["vcpu"], ["cpu cores"], ["cores"]], section: "Application Details" },
  { label: "RAM (GB)", containsAny: [["memory per server"], ["memory"], ["ram"]], section: "Application Details" },
  { label: "Chipset", containsAny: [["chipset"], ["processor family"], ["cpu type"], ["architecture"]], section: "Application Details" },
  { label: "Storage (GB)", containsAny: [["local storage"], ["storage"], ["disk"]], section: "Application Details" },
];

const els = {
  fileInput: document.querySelector("#fileInput"),
  dropZone: document.querySelector("#dropZone"),
  uploadStatus: document.querySelector("#uploadStatus"),
  uploadPanel: document.querySelector("#uploadPanel"),
  intakePage: document.querySelector("#intakePage"),
  shapePage: document.querySelector("#shapePage"),
  reviewPanel: document.querySelector("#reviewPanel"),
  resultsPage: document.querySelector("#resultsPage"),
  reviewTable: document.querySelector("#reviewTable"),
  sheetMeta: document.querySelector("#sheetMeta"),
  rowCount: document.querySelector("#rowCount"),
  columnCount: document.querySelector("#columnCount"),
  approvedCount: document.querySelector("#approvedCount"),
  sheetName: document.querySelector("#sheetName"),
  addRow: document.querySelector("#addRow"),
  priceButton: document.querySelector("#priceButton"),
  priceShapeButton: document.querySelector("#priceShapeButton"),
  backToReviewFromShape: document.querySelector("#backToReviewFromShape"),
  shapeGrid: document.querySelector("#shapeGrid"),
  shapeRateTable: document.querySelector("#shapeRateTable"),
  shapeFamily: document.querySelector("#shapeFamily"),
  shapeDetailTitle: document.querySelector("#shapeDetailTitle"),
  shapeDetailSummary: document.querySelector("#shapeDetailSummary"),
  rateCard: document.querySelector("#rateCard"),
  rateCardShape: document.querySelector("#rateCardShape"),
  pricingSummary: document.querySelector("#pricingSummary"),
  engineStatus: document.querySelector("#engineStatus"),
  backToReview: document.querySelector("#backToReview"),
  rerunPricing: document.querySelector("#rerunPricing"),
  resultsShape: document.querySelector("#resultsShape"),
  resultsSubtitle: document.querySelector("#resultsSubtitle"),
  resultsKpis: document.querySelector("#resultsKpis"),
  costDonut: document.querySelector("#costDonut"),
  costLegend: document.querySelector("#costLegend"),
  topWorkloads: document.querySelector("#topWorkloads"),
  resourceFootprint: document.querySelector("#resourceFootprint"),
  llmNotes: document.querySelector("#llmNotes"),
  resultsEngine: document.querySelector("#resultsEngine"),
  resultRowCount: document.querySelector("#resultRowCount"),
  resultsTable: document.querySelector("#resultsTable"),
  steps: document.querySelectorAll(".step"),
};

function setStep(step) {
  els.steps.forEach((item) => {
    item.classList.toggle("is-active", item.dataset.step === step);
  });
}

function formatCurrency(value) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(Number(value || 0));
}

function formatNumber(value) {
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 2,
  }).format(Number(value || 0));
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function percent(value, total) {
  if (!total) return 0;
  return Math.max(0, Math.min(100, (Number(value || 0) / total) * 100));
}

function normalizeText(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function selectedShape() {
  return (
    state.rateCards.find((shape) => shape.key === state.selectedShape) ||
    state.rateCards[0] || {
      key: state.selectedShape,
      label: "Selected shape",
      family: "OCI flex shape",
      summary: "Selected shape rates will be applied to approved rows.",
      computeRate: 0,
      memoryRate: 0,
      rateCard: state.rateCard,
    }
  );
}

function setShape(shapeKey) {
  const shape = state.rateCards.find((item) => item.key === shapeKey);
  if (!shape) return;
  state.selectedShape = shape.key;
  state.rateCard = shape.rateCard || [];
  state.pricing = null;
  renderRateCard();
  renderShapeChoices();
  renderShapeDetail();
  els.engineStatus.textContent = `${shape.label} selected`;
}

async function fetchJson(url, options = {}, timeoutMs = 60000) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    const payload = await response.json();
    return { response, payload };
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("The request took too long. Please refresh and try again.");
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

function findField(rule) {
  const matchGroups = (rule.containsAny || [rule.contains || []]).map((group) => group.map(normalizeText));
  const section = normalizeText(rule.section);
  const match = state.fields.find((field) => {
    const label = ` ${normalizeText(field.label)} `;
    if (section && !label.trim().startsWith(section)) return false;
    return matchGroups.some((terms) => terms.every((term) => label.includes(` ${term} `) || label.includes(term)));
  });
  return match ? { ...match, label: rule.label } : null;
}

function previewFields() {
  return PREVIEW_FIELD_RULES.map(findField).filter(Boolean);
}

function renderRateCard() {
  els.rateCard.innerHTML = "";
  const shape = selectedShape();
  els.rateCardShape.textContent = shape.label || "Selected shape";
  state.rateCard.forEach((item) => {
    const row = document.createElement("div");
    row.className = "rate-row";
    row.innerHTML = `
      <strong>${escapeHtml(item.sku)}</strong>
      <span>${escapeHtml(item.description)}</span>
      <em>$${Number(item.rate).toFixed(4)}</em>
    `;
    els.rateCard.append(row);
  });
}

function renderShapeChoices() {
  if (!els.shapeGrid) return;
  els.shapeGrid.innerHTML = state.rateCards
    .map((shape) => {
      const isSelected = shape.key === state.selectedShape;
      return `
        <button class="shape-card ${isSelected ? "is-selected" : ""}" type="button" data-shape="${escapeHtml(shape.key)}" style="--shape-accent:${escapeHtml(shape.accent || "#c74634")}">
          <span class="shape-card-top">
            <strong>${escapeHtml(shape.label)}</strong>
            <em>${isSelected ? "Selected" : "Choose"}</em>
          </span>
          <span class="shape-family">${escapeHtml(shape.family || "OCI flex shape")}</span>
          <span class="shape-summary">${escapeHtml(shape.summary || "")}</span>
          <span class="shape-metrics">
            <span><b>$${Number(shape.computeRate || 0).toFixed(4)}</b><small>OCPU/hr</small></span>
            <span><b>$${Number(shape.memoryRate || 0).toFixed(4)}</b><small>GB/hr</small></span>
          </span>
        </button>
      `;
    })
    .join("");

  els.shapeGrid.querySelectorAll("[data-shape]").forEach((button) => {
    button.addEventListener("click", () => setShape(button.dataset.shape));
  });
}

function renderShapeDetail() {
  const shape = selectedShape();
  const rateCard = shape.rateCard || state.rateCard || [];
  els.shapeFamily.textContent = shape.family || "OCI flex shape";
  els.shapeDetailTitle.textContent = shape.label || "Selected shape";
  els.shapeDetailSummary.textContent = shape.summary || "Selected shape rates will be applied to approved rows.";
  els.shapeRateTable.innerHTML = `
    <thead>
      <tr>
        <th>SKU</th>
        <th>Description</th>
        <th>Rate</th>
        <th>Notes</th>
      </tr>
    </thead>
    <tbody>
      ${rateCard
        .map(
          (item) => `
            <tr>
              <td>${escapeHtml(item.sku)}</td>
              <td>${escapeHtml(item.description)}</td>
              <td>$${Number(item.rate || 0).toFixed(4)}</td>
              <td>${escapeHtml(item.notes || item.unit || "")}</td>
            </tr>
          `,
        )
        .join("")}
      <tr>
        <td>-</td>
        <td>Hours per month (constant)</td>
        <td>${formatNumber(shape.hoursPerMonth || 730)}</td>
        <td>Used in compute and memory calculations</td>
      </tr>
    </tbody>
  `;
}

function renderStats(meta = {}) {
  const approved = state.rows.filter((row) => row.__approved !== false).length;
  els.rowCount.textContent = meta.rowCount ?? state.rows.length;
  els.columnCount.textContent = previewFields().length;
  els.approvedCount.textContent = approved;
  els.sheetName.textContent = meta.sheetName || els.sheetName.textContent || "-";
}

function renderTable() {
  const fields = previewFields();
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  headRow.append(headerCell("Approve"));
  fields.forEach((field) => headRow.append(headerCell(field.label)));
  thead.append(headRow);

  const tbody = document.createElement("tbody");
  state.rows.forEach((row, rowIndex) => {
    const tr = document.createElement("tr");
    const approveCell = document.createElement("td");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = row.__approved !== false;
    checkbox.addEventListener("change", () => {
      row.__approved = checkbox.checked;
      renderStats();
    });
    approveCell.append(checkbox);
    tr.append(approveCell);

    fields.forEach((field) => {
      const td = document.createElement("td");
      const input = document.createElement("input");
      input.type = "text";
      input.value = row[field.key] ?? "";
      input.setAttribute("aria-label", `${field.label}, row ${rowIndex + 1}`);
      input.addEventListener("input", () => {
        row[field.key] = input.value;
      });
      td.append(input);
      tr.append(td);
    });
    tbody.append(tr);
  });

  els.reviewTable.replaceChildren(thead, tbody);
  renderStats();
}

function headerCell(label) {
  const th = document.createElement("th");
  th.scope = "col";
  th.textContent = label;
  return th;
}

async function uploadFile(file) {
  if (!file) return;
  els.uploadStatus.textContent = `Uploading and analyzing ${file.name} with the LLM...`;
  els.uploadStatus.style.color = "var(--muted)";
  const body = new FormData();
  body.append("file", file);

  const { response, payload } = await fetchJson(
    "/api/upload",
    {
      method: "POST",
      body,
    },
    100000,
  );
  if (!response.ok) {
    throw new Error(payload.error || "Upload failed.");
  }

  state.fields = payload.fields;
  state.rows = payload.rows;
  state.rateCards = payload.rateCards || [];
  state.selectedShape = payload.selectedShape?.key || state.selectedShape;
  state.rateCard = selectedShape().rateCard || payload.rateCard || [];
  state.pricing = null;

  els.uploadStatus.textContent = "";
  showIntakePage();
  els.uploadPanel.classList.add("is-hidden");
  els.reviewPanel.classList.remove("is-hidden");
  const parserLabel = payload.metadata?.parser === "llm-assisted" ? "LLM normalized" : "Rule-based parse";
  const grain = payload.metadata?.serverGrain && payload.metadata.serverGrain !== "unknown" ? ` • ${payload.metadata.serverGrain} grain` : "";
  els.sheetMeta.textContent = `${payload.fileName} • sheet "${payload.sheetName}" • ${parserLabel}${grain} • data begins on row ${payload.metadata.dataStartRow}`;
  els.sheetName.textContent = payload.sheetName;
  renderRateCard();
  renderShapeChoices();
  renderShapeDetail();
  renderTable();
  setStep("review");
  els.engineStatus.textContent = payload.metadata?.parser === "llm-assisted" ? "LLM normalized upload" : "Ready for approval";
  els.pricingSummary.className = "empty-state";
  const notes = payload.metadata?.extractionNotes || [];
  const warning = payload.llmWarning ? `${payload.llmWarning} ` : "";
  els.pricingSummary.textContent =
    warning ||
    (notes.length
      ? `Review the normalized rows. ${notes.slice(0, 2).join(" ")}`
      : "Review the rows, make adjustments, then choose the OCI flex shape to price.");
}

function setUploadingError(error) {
  els.uploadStatus.textContent = error.message;
  els.uploadStatus.style.color = "var(--danger)";
}

function addBlankRow() {
  const row = {
    __id: `manual-${Date.now()}`,
    __sourceRow: "manual",
    __approved: true,
  };
  state.fields.forEach((field) => {
    row[field.key] = "";
  });
  state.rows.push(row);
  renderTable();
}

async function priceRows() {
  els.priceButton.disabled = true;
  els.priceButton.textContent = "Pricing...";
  els.priceShapeButton.disabled = true;
  els.priceShapeButton.textContent = "Pricing...";
  els.rerunPricing.disabled = true;
  els.rerunPricing.textContent = "Pricing...";
  els.engineStatus.textContent = `Mapping SKUs for ${selectedShape().label}`;

  try {
    const { response, payload } = await fetchJson(
      "/api/price",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fields: state.fields, rows: state.rows, shape: state.selectedShape }),
      },
      70000,
    );
    if (!response.ok) {
      throw new Error(payload.error || "Pricing failed.");
    }
    state.pricing = payload;
    renderPricing(payload);
    renderResults(payload);
    showResultsPage();
    setStep("price");
  } catch (error) {
    els.engineStatus.textContent = "Pricing error";
    els.pricingSummary.className = "empty-state";
    els.pricingSummary.textContent = error.message;
  } finally {
    els.priceButton.disabled = false;
    els.priceButton.textContent = "Continue to shape";
    els.priceShapeButton.disabled = false;
    els.priceShapeButton.textContent = "Price with LLM";
    els.rerunPricing.disabled = false;
    els.rerunPricing.textContent = "Reprice with LLM";
  }
}

function renderPricing(pricing) {
  const shape = pricing.selectedShape || selectedShape();
  els.engineStatus.textContent = `${shape.label}: ${pricing.engine === "llm-assisted" ? "LLM-assisted" : "Local mapping"}`;
  els.pricingSummary.className = "pricing-result";

  const warning = pricing.llmWarning ? `<p class="warning">${pricing.llmWarning}</p>` : "";
  const rows = pricing.rows
    .slice()
    .sort((a, b) => b.monthly - a.monthly)
    .slice(0, 10)
    .map(
      (row) => `
        <tr>
          <td>${escapeHtml(row.name || row.rowId)}</td>
          <td>${escapeHtml(row.environment || "-")}</td>
          <td>${formatCurrency(row.monthly)}</td>
        </tr>
      `,
    )
    .join("");

  els.pricingSummary.innerHTML = `
    ${warning}
    <div class="kpis">
      <div class="kpi"><span>Monthly</span><strong>${formatCurrency(pricing.totals.monthly)}</strong></div>
      <div class="kpi"><span>Annual</span><strong>${formatCurrency(pricing.totals.annual)}</strong></div>
      <div class="kpi"><span>OCPUs</span><strong>${formatNumber(pricing.totals.ocpus)}</strong></div>
      <div class="kpi"><span>Shape</span><strong>${escapeHtml(shape.shortLabel || shape.label)}</strong></div>
    </div>
    <table class="result-table">
      <thead>
        <tr><th>Application</th><th>Env</th><th>Monthly</th></tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function showIntakePage() {
  els.intakePage.classList.remove("is-hidden");
  els.shapePage.classList.add("is-hidden");
  els.resultsPage.classList.add("is-hidden");
  if (state.rows.length) {
    setStep("review");
  } else {
    setStep("upload");
  }
}

function showShapePage() {
  if (!state.rows.length) return;
  els.intakePage.classList.add("is-hidden");
  els.shapePage.classList.remove("is-hidden");
  els.resultsPage.classList.add("is-hidden");
  renderShapeChoices();
  renderShapeDetail();
  setStep("shape");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showResultsPage() {
  els.intakePage.classList.add("is-hidden");
  els.shapePage.classList.add("is-hidden");
  els.resultsPage.classList.remove("is-hidden");
  setStep("price");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function aggregateSkuCosts(pricing) {
  const bySku = new Map();
  pricing.rows.forEach((row) => {
    row.lineItems.forEach((item) => {
      const current = bySku.get(item.sku) || {
        sku: item.sku,
        description: item.description,
        monthly: 0,
      };
      current.monthly += item.monthly;
      bySku.set(item.sku, current);
    });
  });
  return [...bySku.values()].sort((a, b) => b.monthly - a.monthly);
}

function renderResults(pricing) {
  const topRows = pricing.rows.slice().sort((a, b) => b.monthly - a.monthly);
  const skuCosts = aggregateSkuCosts(pricing);
  const maxMonthly = topRows[0]?.monthly || 1;
  const engineLabel = pricing.engine === "llm-assisted" ? "LLM-assisted" : "Rule-based fallback";
  const shape = pricing.selectedShape || selectedShape();

  els.resultsShape.textContent = shape.label || "Selected shape";
  els.resultsSubtitle.textContent = `${pricing.rows.length} approved rows priced on ${shape.label} with ${engineLabel.toLowerCase()} SKU validation.`;
  els.resultsEngine.textContent = engineLabel;
  els.resultRowCount.textContent = `${pricing.rows.length} workloads`;

  els.resultsKpis.innerHTML = `
    <div class="result-kpi primary">
      <span>Monthly run rate</span>
      <strong>${formatCurrency(pricing.totals.monthly)}</strong>
      <em>${formatCurrency(pricing.totals.annual)} annualized</em>
    </div>
    <div class="result-kpi">
      <span>Flex shape</span>
      <strong>${escapeHtml(shape.shortLabel || shape.label)}</strong>
      <em>$${Number(shape.computeRate || 0).toFixed(4)} OCPU/hr and $${Number(shape.memoryRate || 0).toFixed(4)} GB/hr</em>
    </div>
    <div class="result-kpi">
      <span>Compute</span>
      <strong>${formatNumber(pricing.totals.ocpus)} OCPUs</strong>
      <em>2 vCPU = 1 OCPU</em>
    </div>
    <div class="result-kpi">
      <span>Memory</span>
      <strong>${formatNumber(pricing.totals.memoryGb)} GB</strong>
      <em>GB-hours at 730 hrs/mo</em>
    </div>
  `;

  renderCostMix(skuCosts, pricing.totals.monthly);
  renderTopWorkloads(topRows, maxMonthly);
  renderResourceFootprint(pricing);
  renderLlmNotes(pricing);
  renderResultsTable(topRows);
}

function renderCostMix(skuCosts, total) {
  const colors = ["#c74634", "#2f6f73", "#d4b483", "#7a3126"];
  let running = 0;
  const stops = skuCosts
    .map((item, index) => {
      const start = running;
      const share = percent(item.monthly, total);
      running += share;
      const color = colors[index % colors.length];
      return `${color} ${start}% ${running}%`;
    })
    .join(", ");
  els.costDonut.style.background = `conic-gradient(${stops || "#dedbd3 0 100%"})`;
  els.costDonut.innerHTML = `<span>${formatCurrency(total)}<em>/mo</em></span>`;
  els.costLegend.innerHTML = skuCosts
    .map((item, index) => {
      const color = colors[index % colors.length];
      return `
        <div class="legend-row">
          <i style="background:${color}"></i>
          <span>${escapeHtml(item.sku)}</span>
          <strong>${formatCurrency(item.monthly)}</strong>
          <em>${escapeHtml(item.description)}</em>
        </div>
      `;
    })
    .join("");
}

function renderTopWorkloads(rows, maxMonthly) {
  els.topWorkloads.innerHTML = rows
    .slice(0, 8)
    .map((row) => {
      const width = Math.max(4, percent(row.monthly, maxMonthly));
      return `
        <div class="bar-row">
          <div>
            <strong>${escapeHtml(row.name || row.rowId)}</strong>
            <span>${escapeHtml(row.environment || "No environment")}</span>
          </div>
          <div class="bar-track"><i style="width:${width}%"></i></div>
          <em>${formatCurrency(row.monthly)}</em>
        </div>
      `;
    })
    .join("");
}

function renderResourceFootprint(pricing) {
  const resources = [
    { label: "OCPUs", value: pricing.totals.ocpus, suffix: "", color: "#c74634" },
    { label: "Memory", value: pricing.totals.memoryGb, suffix: "GB", color: "#2f6f73" },
    { label: "Block storage", value: pricing.totals.blockStorageGb, suffix: "GB", color: "#d4b483" },
    { label: "File storage", value: pricing.totals.fileStorageGb, suffix: "GB", color: "#7a3126" },
  ];
  const maxValue = Math.max(...resources.map((item) => item.value), 1);
  els.resourceFootprint.innerHTML = resources
    .map((item) => `
      <div class="resource-row">
        <span>${item.label}</span>
        <div class="resource-meter"><i style="width:${percent(item.value, maxValue)}%; background:${item.color}"></i></div>
        <strong>${formatNumber(item.value)} ${item.suffix}</strong>
      </div>
    `)
    .join("");
}

function noteItems(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value;
  if (typeof value === "string") return [value];
  if (typeof value === "object") return Object.values(value);
  return [String(value)];
}

function noteText(note) {
  if (typeof note === "string") return note;
  if (!note || typeof note !== "object") return String(note || "");
  return note.note || note.rule || note.message || note.text || JSON.stringify(note);
}

function renderLlmNotes(pricing) {
  const notes = [];
  if (pricing.llmWarning) {
    notes.push(pricing.llmWarning);
  }
  noteItems(pricing.reviewNotes).forEach((note) => notes.push(noteText(note)));
  noteItems(pricing.globalAssumptions).forEach((note) => notes.push(noteText(note)));
  if (!notes.length) {
    notes.push("SKU rules were validated against the rate card and approved rows.");
    notes.push("Review storage assumptions for workloads that rely on NAS, shared mounts, or database-only allocation.");
  }
  els.llmNotes.innerHTML = notes
    .slice(0, 6)
    .map((note) => `<p>${escapeHtml(note)}</p>`)
    .join("");
}

function renderResultsTable(rows) {
  const head = `
    <thead>
      <tr>
        <th>Application</th>
        <th>Env</th>
        <th>OCPUs</th>
        <th>Memory</th>
        <th>Storage</th>
        <th>Monthly</th>
        <th>Annual</th>
      </tr>
    </thead>
  `;
  const body = rows
    .map((row) => `
      <tr>
        <td>${escapeHtml(row.name || row.rowId)}</td>
        <td>${escapeHtml(row.environment || "-")}</td>
        <td>${formatNumber(row.specs.ocpus)}</td>
        <td>${formatNumber(row.specs.memoryGb)} GB</td>
        <td>${formatNumber(row.specs.blockStorageGb + row.specs.fileStorageGb)} GB</td>
        <td>${formatCurrency(row.monthly)}</td>
        <td>${formatCurrency(row.annual)}</td>
      </tr>
    `)
    .join("");
  els.resultsTable.innerHTML = `${head}<tbody>${body}</tbody>`;
}

els.fileInput.addEventListener("change", () => {
  uploadFile(els.fileInput.files[0]).catch(setUploadingError);
});

["dragenter", "dragover"].forEach((eventName) => {
  els.dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    els.dropZone.classList.add("is-dragging");
  });
});

["dragleave", "drop"].forEach((eventName) => {
  els.dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    els.dropZone.classList.remove("is-dragging");
  });
});

els.dropZone.addEventListener("drop", (event) => {
  const [file] = event.dataTransfer.files;
  uploadFile(file).catch(setUploadingError);
});

els.addRow.addEventListener("click", addBlankRow);
els.priceButton.addEventListener("click", showShapePage);
els.priceShapeButton.addEventListener("click", priceRows);
els.rerunPricing.addEventListener("click", priceRows);
els.backToReview.addEventListener("click", showIntakePage);
els.backToReviewFromShape.addEventListener("click", showIntakePage);

fetch("/api/health")
  .then((response) => response.json())
  .then((payload) => {
    state.rateCards = payload.rateCards || [];
    state.selectedShape = payload.selectedShape?.key || state.selectedShape;
    state.rateCard = selectedShape().rateCard || payload.rateCard || [];
    renderRateCard();
    renderShapeChoices();
    renderShapeDetail();
  })
  .catch(() => {
    els.engineStatus.textContent = "Backend unavailable";
  });
