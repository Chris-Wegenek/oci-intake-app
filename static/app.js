const state = {
  fields: [],
  rows: [],
  rateCard: [],
  pricing: null,
};

const PREVIEW_FIELD_RULES = [
  { label: "Application Name", contains: ["application name"] },
  { label: "Environment", contains: ["environment"] },
  { label: "Application Details", contains: ["application type"], section: "Application Details" },
  { label: "Application Version", contains: ["application version"], section: "Application Details" },
  { label: "Operating System", contains: ["operating system"], section: "Application Details" },
  { label: "CPUs", contains: ["number of cpu cores per server"], section: "Application Details" },
  { label: "RAM (GB)", contains: ["memory per server"], section: "Application Details" },
  { label: "Chipset", contains: ["chipset"], section: "Application Details" },
  { label: "Storage (GB)", contains: ["local storage"], section: "Application Details" },
];

const els = {
  fileInput: document.querySelector("#fileInput"),
  dropZone: document.querySelector("#dropZone"),
  uploadStatus: document.querySelector("#uploadStatus"),
  uploadPanel: document.querySelector("#uploadPanel"),
  reviewPanel: document.querySelector("#reviewPanel"),
  reviewTable: document.querySelector("#reviewTable"),
  sheetMeta: document.querySelector("#sheetMeta"),
  rowCount: document.querySelector("#rowCount"),
  columnCount: document.querySelector("#columnCount"),
  approvedCount: document.querySelector("#approvedCount"),
  sheetName: document.querySelector("#sheetName"),
  addRow: document.querySelector("#addRow"),
  priceButton: document.querySelector("#priceButton"),
  rateCard: document.querySelector("#rateCard"),
  pricingSummary: document.querySelector("#pricingSummary"),
  engineStatus: document.querySelector("#engineStatus"),
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

function normalizeText(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function findField(rule) {
  const terms = rule.contains.map(normalizeText);
  const section = normalizeText(rule.section);
  const match = state.fields.find((field) => {
    const label = normalizeText(field.label);
    if (section && !label.startsWith(section)) return false;
    return terms.every((term) => label.includes(term));
  });
  return match ? { ...match, label: rule.label } : null;
}

function previewFields() {
  return PREVIEW_FIELD_RULES.map(findField).filter(Boolean);
}

function renderRateCard() {
  els.rateCard.innerHTML = "";
  state.rateCard.forEach((item) => {
    const row = document.createElement("div");
    row.className = "rate-row";
    row.innerHTML = `
      <strong>${item.sku}</strong>
      <span>${item.description}</span>
      <em>$${Number(item.rate).toFixed(4)}</em>
    `;
    els.rateCard.append(row);
  });
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
  els.uploadStatus.textContent = `Uploading ${file.name}...`;
  const body = new FormData();
  body.append("file", file);

  const response = await fetch("/api/upload", {
    method: "POST",
    body,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Upload failed.");
  }

  state.fields = payload.fields;
  state.rows = payload.rows;
  state.rateCard = payload.rateCard;
  state.pricing = null;

  els.uploadStatus.textContent = "";
  els.uploadPanel.classList.add("is-hidden");
  els.reviewPanel.classList.remove("is-hidden");
  els.sheetMeta.textContent = `${payload.fileName} • sheet "${payload.sheetName}" • data begins on row ${payload.metadata.dataStartRow}`;
  els.sheetName.textContent = payload.sheetName;
  renderRateCard();
  renderTable();
  setStep("review");
  els.engineStatus.textContent = "Ready for approval";
  els.pricingSummary.className = "empty-state";
  els.pricingSummary.textContent = "Review the rows, make adjustments, then approve and price.";
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
  els.engineStatus.textContent = "Mapping SKUs";

  try {
    const response = await fetch("/api/price", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fields: state.fields, rows: state.rows }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Pricing failed.");
    }
    state.pricing = payload;
    renderPricing(payload);
    setStep("price");
  } catch (error) {
    els.engineStatus.textContent = "Pricing error";
    els.pricingSummary.className = "empty-state";
    els.pricingSummary.textContent = error.message;
  } finally {
    els.priceButton.disabled = false;
    els.priceButton.textContent = "Approve and price with LLM";
  }
}

function renderPricing(pricing) {
  els.engineStatus.textContent = pricing.engine === "llm-assisted" ? "LLM-assisted" : "Local mapping";
  els.pricingSummary.className = "pricing-result";

  const warning = pricing.llmWarning ? `<p class="warning">${pricing.llmWarning}</p>` : "";
  const rows = pricing.rows
    .slice()
    .sort((a, b) => b.monthly - a.monthly)
    .slice(0, 10)
    .map(
      (row) => `
        <tr>
          <td>${row.name || row.rowId}</td>
          <td>${row.environment || "-"}</td>
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
      <div class="kpi"><span>Memory GB</span><strong>${formatNumber(pricing.totals.memoryGb)}</strong></div>
    </div>
    <table class="result-table">
      <thead>
        <tr><th>Application</th><th>Env</th><th>Monthly</th></tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
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
els.priceButton.addEventListener("click", priceRows);

fetch("/api/health")
  .then((response) => response.json())
  .then((payload) => {
    state.rateCard = payload.rateCard || [];
    renderRateCard();
  })
  .catch(() => {
    els.engineStatus.textContent = "Backend unavailable";
  });
