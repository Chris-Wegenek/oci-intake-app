const state = {
  fields: [],
  rows: [],
  rateCard: [],
  rateCards: [],
  fullServiceCatalog: [],
  selectedShape: "e6-standard-ax",
  selectedVendor: "amd",
  lastShapeByVendor: {
    amd: "e6-standard-ax",
  },
  pricing: null,
  intakeMode: "on_prem",
  providerHint: "auto",
  uploadMetadata: {},
  fullServiceBeta: false,
  bomMatch: false,
  hideGpuPricing: false,
  hideWindowsPricing: false,
  rightsize: false,
  existingInfraCost: 0,
  showMissingOnly: false,
  openaiApiEnabled: false,
  openaiApiConfigured: false,
  openaiApiConnected: false,
  openaiModel: "",
  resultSort: {
    key: "monthly",
    direction: "desc",
  },
  ramp: {
    months: 36,
    ceiling: 0,
    nextPointId: 1,
    selectedPointId: null,
    points: [],
  },
};

const PROCESSOR_VENDORS = [
  {
    key: "amd",
    label: "AMD",
    description: "AMD-based E-series flexible shapes.",
  },
  {
    key: "intel",
    label: "Intel",
    description: "Intel-based X-series standard and Ax shapes.",
  },
];

let activeFill = null;

const PREVIEW_FIELD_RULES = [
  { label: "Application Name", contains: ["application name"] },
  { label: "Environment", contains: ["environment"] },
  { label: "OCPUs", containsAny: [["ocpus per server"], ["ocpu"], ["number of cpu cores per server"], ["number of cpus"], ["vcpu"], ["cpu cores"], ["cores"]] },
  { label: "RAM (GB)", containsAny: [["memory per server"], ["memory"], ["ram"]] },
  { label: "Storage (GB)", containsAny: [["local storage"], ["shared storage"], ["total allocated storage"], ["database size"], ["total storage"], ["storage gb"], ["disk gb"]] },
];

const FULL_SERVICE_PREVIEW_FIELD_RULES = [
  { label: "Provider", containsAny: [["source provider"], ["provider"], ["cloud provider"], ["vendor"]] },
  { label: "Source Service", containsAny: [["source service"], ["service name"], ["meter category"], ["product code"]] },
  { label: "Source Product", containsAny: [["source product"], ["usage type"], ["meter name"], ["sku name"], ["item description"]] },
  { label: "Usage Qty", containsAny: [["usage quantity"], ["usage amount"], ["consumed quantity"], ["quantity"]] },
  { label: "Usage Unit", containsAny: [["usage unit"], ["unit of measure"], ["pricing unit"], ["meter unit"]] },
  { label: "Source Cost", containsAny: [["source monthly cost"], ["monthly cost"], ["amortized cost"], ["unblended cost"]] },
];

const CLOUD_BILL_PREVIEW_FIELD_RULES = [
  { label: "Provider", containsAny: [["provider"], ["source provider"], ["cloud provider"]] },
  { label: "Account / Project", containsAny: [["account"], ["project"], ["subscription"]] },
  { label: "Source Service", containsAny: [["source service"], ["service"], ["meter category"], ["product code"]] },
  { label: "SKU / Meter", containsAny: [["sku"], ["meter"], ["usage type"], ["source product"], ["line item description"]] },
  { label: "Region", containsAny: [["region"], ["resource location"], ["location"]] },
  { label: "Usage Qty", containsAny: [["usage quantity"], ["usage amount"], ["quantity"], ["consumed quantity"]] },
  { label: "Usage Unit", containsAny: [["usage unit"], ["unit of measure"], ["pricing unit"], ["unit"]] },
  { label: "OCPUs", containsAny: [["ocpu"], ["vcpu"], ["cpu"], ["core count"], ["cores"]] },
  { label: "RAM (GB)", containsAny: [["ram"], ["memory"], ["memory gb"], ["ram gb"]] },
  { label: "Source Cost", containsAny: [["source cost"], ["source monthly cost"], ["cost"], ["unblended cost"]] },
  { label: "Currency", containsAny: [["currency"], ["billing currency"]] },
  { label: "OCI Service", containsAny: [["oci service"], ["oci service category"], ["target service"]] },
  { label: "OCI Product", containsAny: [["oci product"], ["target product"], ["mapped sku"]] },
  { label: "Confidence", containsAny: [["mapping confidence"], ["confidence"], ["review status"]] },
];

const MANUAL_REVIEW_FIELDS = [
  { key: "application_name", label: "Application Name" },
  { key: "environment", label: "Environment" },
  {
    key: "application_details_number_of_cpu_cores_per_server",
    label: "Application Details: OCPUs",
  },
  { key: "application_details_memory_per_server_gb", label: "Application Details: Memory per server (GB)" },
  { key: "application_details_local_storage_gb", label: "Application Details: Local Storage (GB)" },
];

const els = {
  fileInput: document.querySelector("#fileInput"),
  dropZone: document.querySelector("#dropZone"),
  modeOnPrem: document.querySelector("#modeOnPrem"),
  modeCloudBill: document.querySelector("#modeCloudBill"),
  modeEyebrow: document.querySelector("#modeEyebrow"),
  uploadHeading: document.querySelector("#uploadHeading"),
  uploadDescription: document.querySelector("#uploadDescription"),
  dropZoneHint: document.querySelector("#dropZoneHint"),
  providerControl: document.querySelector("#providerControl"),
  providerHint: document.querySelector("#providerHint"),
  uploadStatus: document.querySelector("#uploadStatus"),
  uploadProgress: document.querySelector("#uploadProgress"),
  uploadProgressDetail: document.querySelector("#uploadProgressDetail"),
  uploadPanel: document.querySelector("#uploadPanel"),
  intakePage: document.querySelector("#intakePage"),
  pricingRail: document.querySelector("#pricingRail"),
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
  addColumn: document.querySelector("#addColumn"),
  addColumnForm: document.querySelector("#addColumnForm"),
  newColumnName: document.querySelector("#newColumnName"),
  cancelAddColumn: document.querySelector("#cancelAddColumn"),
  missingOnlyToggle: document.querySelector("#missingOnlyToggle"),
  missingOnlySummary: document.querySelector("#missingOnlySummary"),
  tableEditPrompt: document.querySelector("#tableEditPrompt"),
  applyTableEdit: document.querySelector("#applyTableEdit"),
  tableEditStatus: document.querySelector("#tableEditStatus"),
  priceButton: document.querySelector("#priceButton"),
  priceShapeButton: document.querySelector("#priceShapeButton"),
  bomMatchToggle: document.querySelector("#bomMatchToggle"),
  hideGpuToggle: document.querySelector("#hideGpuToggle"),
  hideWindowsToggle: document.querySelector("#hideWindowsToggle"),
  rightsizeSwitch: document.querySelector("#rightsizeSwitch"),
  exportExcel: document.querySelector("#exportExcel"),
  backToReviewFromShape: document.querySelector("#backToReviewFromShape"),
  processorPicker: document.querySelector("#processorPicker"),
  shapeDropdown: document.querySelector("#shapeDropdown"),
  shapeVendorTitle: document.querySelector("#shapeVendorTitle"),
  shapeVendorDescription: document.querySelector("#shapeVendorDescription"),
  shapeVendorCount: document.querySelector("#shapeVendorCount"),
  shapeGrid: document.querySelector("#shapeGrid"),
  shapeFamily: document.querySelector("#shapeFamily"),
  shapeDetailTitle: document.querySelector("#shapeDetailTitle"),
  shapeDetailSummary: document.querySelector("#shapeDetailSummary"),
  shapeDetailRates: document.querySelector("#shapeDetailRates"),
  rateCard: document.querySelector("#rateCard"),
  rateCardShape: document.querySelector("#rateCardShape"),
  pricingSummary: document.querySelector("#pricingSummary"),
  engineStatus: document.querySelector("#engineStatus"),
  backToReview: document.querySelector("#backToReview"),
  rerunPricing: document.querySelector("#rerunPricing"),
  resultsShape: document.querySelector("#resultsShape"),
  resultsSubtitle: document.querySelector("#resultsSubtitle"),
  resultsKpis: document.querySelector("#resultsKpis"),
  rampCeilingLabel: document.querySelector("#rampCeilingLabel"),
  rampChart: document.querySelector("#rampChart"),
  rampPeakMonth: document.querySelector("#rampPeakMonth"),
  rampPeakMonthly: document.querySelector("#rampPeakMonthly"),
  addRampPoint: document.querySelector("#addRampPoint"),
  removeRampPoint: document.querySelector("#removeRampPoint"),
  rampThreeYearTotal: document.querySelector("#rampThreeYearTotal"),
  rampAvgMonthly: document.querySelector("#rampAvgMonthly"),
  rampYearOneTotal: document.querySelector("#rampYearOneTotal"),
  rampYearTwoTotal: document.querySelector("#rampYearTwoTotal"),
  rampYearThreeTotal: document.querySelector("#rampYearThreeTotal"),
  costDonut: document.querySelector("#costDonut"),
  costLegend: document.querySelector("#costLegend"),
  topListHeading: document.querySelector("#topListHeading"),
  topWorkloads: document.querySelector("#topWorkloads"),
  detailHeading: document.querySelector("#detailHeading"),
  resultRowCount: document.querySelector("#resultRowCount"),
  resultsTable: document.querySelector("#resultsTable"),
  steps: document.querySelectorAll(".step"),
};

function setStep(step) {
  els.steps.forEach((item) => {
    const isActive = item.dataset.step === step;
    item.classList.toggle("is-active", isActive);
    if (isActive) {
      item.setAttribute("aria-current", "step");
    } else {
      item.removeAttribute("aria-current");
    }
  });
}

function formatCurrency(value) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(Number(value || 0));
}

function formatCompactCurrency(value) {
  const amount = Number(value || 0);
  if (Math.abs(amount) < 10000) return formatCurrency(amount);
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: Math.abs(amount) >= 1000000 ? 2 : 1,
  }).format(amount);
}

function formatCompactNumber(value) {
  const amount = Number(value || 0);
  if (Math.abs(amount) < 10000) return formatNumber(amount);
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: Math.abs(amount) >= 1000000 ? 2 : 1,
  }).format(amount);
}

function formatKpiQuantity(value, unit) {
  return `${formatCompactNumber(value)} ${unit}`;
}

function formatNumber(value) {
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 2,
  }).format(Number(value || 0));
}

function clamp(value, min, max) {
  return Math.min(Math.max(Number(value) || 0, min), max);
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

function fieldKeyFromLabel(label) {
  const slug = normalizeText(label).replace(/\s+/g, "_") || "column";
  return `custom_${slug}`;
}

function uniqueFieldKey(label) {
  const existing = new Set(state.fields.map((field) => field.key));
  const base = fieldKeyFromLabel(label);
  let key = base;
  let index = 2;
  while (existing.has(key)) {
    key = `${base}_${index}`;
    index += 1;
  }
  return key;
}

function isManualField(field) {
  return Boolean(field?.manual || field?.userAdded);
}

function hasCellContent(value) {
  return value !== null && value !== undefined && String(value).trim() !== "";
}

function fieldHasContent(field) {
  if (!field?.key) return false;
  return state.rows.some((row) => hasCellContent(row[field.key]));
}

function shouldShowField(field) {
  return isManualField(field) || fieldHasContent(field);
}

function rowHasMissingData(row, fields = previewFields()) {
  return fields.some((field) => !hasCellContent(row[field.key]));
}

function reviewRowEntries(fields = previewFields()) {
  const entries = state.rows.map((row, rowIndex) => ({ row, rowIndex }));
  if (!state.showMissingOnly) return entries;
  return entries.filter(({ row }) => rowHasMissingData(row, fields));
}

function missingDataRowCount(fields = previewFields()) {
  return state.rows.filter((row) => rowHasMissingData(row, fields)).length;
}

function syncMissingFilterUi(fields = previewFields()) {
  const missingCount = missingDataRowCount(fields);
  if (els.missingOnlyToggle) {
    els.missingOnlyToggle.checked = state.showMissingOnly;
    els.missingOnlyToggle.disabled = !state.rows.length || !fields.length;
  }
  if (els.missingOnlySummary) {
    const rowLabel = missingCount === 1 ? "row" : "rows";
    els.missingOnlySummary.textContent = state.showMissingOnly
      ? `${formatNumber(missingCount)} ${rowLabel} with blanks shown`
      : `${formatNumber(missingCount)} ${rowLabel} with blanks`;
  }
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

function normalizeVendorKey(value) {
  const vendor = String(value || "").toLowerCase();
  if (vendor.includes("intel")) return "intel";
  if (vendor.includes("amd")) return "amd";
  return "";
}

function shapeVendor(shape = {}) {
  const explicit = normalizeVendorKey(shape.processorVendor || shape.vendor || shape.processor);
  if (explicit) return explicit;
  const text = normalizeText([shape.key, shape.label, shape.family].filter(Boolean).join(" "));
  if (text.includes("intel") || text.includes("x9")) return "intel";
  return "amd";
}

function vendorDefinition(vendorKey = state.selectedVendor) {
  return PROCESSOR_VENDORS.find((vendor) => vendor.key === vendorKey) || PROCESSOR_VENDORS[0];
}

function shapesForVendor(vendorKey = state.selectedVendor) {
  return state.rateCards.filter((shape) => shapeVendor(shape) === vendorKey);
}

function syncVendorForSelectedShape() {
  const shape = selectedShape();
  state.selectedVendor = shapeVendor(shape);
  if (shape?.key) {
    state.lastShapeByVendor[state.selectedVendor] = shape.key;
  }
}

function displayRateCard(rateCard = state.rateCard) {
  if (!state.fullServiceBeta) return rateCard || [];
  const items = [...(rateCard || [])];
  const seen = new Set(items.map((item) => item.sku));
  state.fullServiceCatalog.forEach((item) => {
    if (seen.has(item.sku)) return;
    items.push({
      sku: item.sku,
      description: item.description,
      unit: item.unit,
      rate: item.rate,
      notes: item.notes || item.category || item.unit,
    });
    seen.add(item.sku);
  });
  return items;
}

function isCloudBillMode() {
  return state.intakeMode === "cloud_bill";
}

function providerLabel(value = state.providerHint) {
  const labels = {
    auto: "Auto-detect",
    aws: "AWS",
    azure: "Azure",
    gcp: "GCP",
  };
  return labels[value] || "Auto-detect";
}

function pricingActionLabel(action = "price") {
  if (action === "rerun") {
    return state.openaiApiConnected ? "Reprice on OCI" : "Reprice estimate";
  }
  return state.openaiApiConnected ? "Price on OCI" : "Price estimate";
}

function syncApiUi() {
  if (els.priceShapeButton && !els.priceShapeButton.disabled) {
    els.priceShapeButton.textContent = pricingActionLabel("price");
  }
  if (els.rerunPricing && !els.rerunPricing.disabled) {
    els.rerunPricing.textContent = pricingActionLabel("rerun");
  }
  syncModeUi();
  if (!state.rows.length && els.engineStatus) {
    els.engineStatus.textContent = state.openaiApiConnected
      ? `OpenAI enabled: ${state.openaiModel || "configured model"}`
      : state.openaiApiEnabled
        ? "OpenAI API key missing"
        : "OpenAI temporarily disconnected";
  }
}

function renderProcessorPicker() {
  if (!els.processorPicker) return;
  els.processorPicker.innerHTML = PROCESSOR_VENDORS.map((vendor) => {
    const shapes = shapesForVendor(vendor.key);
    const isSelected = vendor.key === state.selectedVendor;
    const shapeCount = shapes.length;
    const countLabel = `${formatNumber(shapeCount)} ${shapeCount === 1 ? "shape" : "shapes"}`;
    const logo =
      vendor.key === "amd"
        ? `<span class="processor-logo amd-logo"><span>AMD</span><i aria-hidden="true"></i></span>`
        : `<span class="processor-logo intel-logo"><span>intel</span></span>`;
    return `
      <button
        class="processor-button ${isSelected ? "is-selected" : ""}"
        type="button"
        data-processor-vendor="${escapeHtml(vendor.key)}"
        aria-expanded="${isSelected ? "true" : "false"}"
        aria-controls="shapeDropdown"
      >
        ${logo}
        <em>${escapeHtml(countLabel)}</em>
      </button>
    `;
  }).join("");

  els.processorPicker.querySelectorAll("[data-processor-vendor]").forEach((button) => {
    button.addEventListener("click", () => setProcessorVendor(button.dataset.processorVendor));
  });
}

function renderShapeVendorMeta() {
  const vendor = vendorDefinition();
  const shapes = shapesForVendor(vendor.key);
  const shapeCount = shapes.length;
  if (els.shapeVendorTitle) {
    els.shapeVendorTitle.textContent = `${vendor.label} shapes`;
  }
  if (els.shapeVendorDescription) {
    els.shapeVendorDescription.textContent = vendor.description;
  }
  if (els.shapeVendorCount) {
    els.shapeVendorCount.textContent = `${formatNumber(shapeCount)} ${shapeCount === 1 ? "shape" : "shapes"}`;
  }
  if (els.shapeDropdown) {
    els.shapeDropdown.dataset.vendor = vendor.key;
  }
}

function setProcessorVendor(vendorKey) {
  const vendor = vendorDefinition(vendorKey).key;
  state.selectedVendor = vendor;
  const shapes = shapesForVendor(vendor);
  const rememberedShape = shapes.find((shape) => shape.key === state.lastShapeByVendor[vendor]);
  const currentShapeInVendor = shapes.some((shape) => shape.key === state.selectedShape);
  const targetShape = currentShapeInVendor ? selectedShape() : rememberedShape || shapes[0];
  if (targetShape && targetShape.key !== state.selectedShape) {
    setShape(targetShape.key);
    return;
  }
  renderProcessorPicker();
  renderShapeChoices();
  renderShapeDetail();
}

function setShape(shapeKey) {
  const shape = state.rateCards.find((item) => item.key === shapeKey);
  if (!shape) return;
  state.selectedShape = shape.key;
  state.selectedVendor = shapeVendor(shape);
  state.lastShapeByVendor[state.selectedVendor] = shape.key;
  state.rateCard = shape.rateCard || [];
  state.pricing = null;
  renderRateCard();
  renderProcessorPicker();
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
  const rules = isCloudBillMode()
    ? CLOUD_BILL_PREVIEW_FIELD_RULES
    : state.fullServiceBeta
    ? [PREVIEW_FIELD_RULES[0], ...FULL_SERVICE_PREVIEW_FIELD_RULES, ...PREVIEW_FIELD_RULES.slice(1)]
    : PREVIEW_FIELD_RULES;
  const fields = [];
  const seen = new Set();
  rules.forEach((rule) => {
    const field = findField(rule);
    if (field && !seen.has(field.key) && shouldShowField(field)) {
      fields.push(field);
      seen.add(field.key);
    }
  });
  state.fields.forEach((field) => {
    if (!field?.key || seen.has(field.key) || !isManualField(field)) return;
    fields.push(field);
    seen.add(field.key);
  });
  return fields;
}

function syncModeUi() {
  const cloudBill = isCloudBillMode();
  state.fullServiceBeta = cloudBill;
  els.modeOnPrem?.classList.toggle("is-selected", !cloudBill);
  els.modeCloudBill?.classList.toggle("is-selected", cloudBill);
  els.providerControl?.classList.toggle("is-hidden", !cloudBill);
  if (els.providerHint) {
    els.providerHint.value = state.providerHint;
  }
  els.fileInput.accept = cloudBill ? ".pdf,.csv,.tsv,.xlsx,.xls" : ".xlsx,.xls";
  els.modeEyebrow.textContent = cloudBill ? "Cloud bill" : "On-prem inventory";
  els.uploadHeading.textContent = cloudBill ? "Upload cloud bill" : "Upload inventory";
  els.uploadDescription.textContent = cloudBill
    ? "Upload an AWS, Azure, or GCP bill export. PDF invoices and CSV, TSV, or Excel exports are mapped to OCI-equivalent services and meters."
    : state.openaiApiConnected
    ? "Drop an Excel workbook here. OpenAI can inspect the workbook, choose the inventory table, and normalize server/application fields for review."
    : "Drop an Excel workbook here. The local parser will choose the inventory table and normalize CPU, RAM, storage, environment, and application fields for review.";
  els.dropZone.querySelector("strong").textContent = cloudBill ? "Choose bill export" : "Choose spreadsheet";
  els.dropZoneHint.textContent = cloudBill
    ? "or drag a PDF, CSV, TSV, or Excel bill export onto this upload area"
    : "or drag the workbook onto this upload area";
}

function setIntakeMode(mode) {
  state.intakeMode = mode === "cloud_bill" ? "cloud_bill" : "on_prem";
  state.providerHint = state.intakeMode === "cloud_bill" ? state.providerHint : "auto";
  syncModeUi();
  state.pricing = null;
  if (state.rows.length) {
    renderTable();
    renderShapeDetail();
    els.engineStatus.textContent = isCloudBillMode() ? "Cloud bill mode" : "On-prem inventory mode";
    els.pricingSummary.className = "empty-state";
    els.pricingSummary.textContent = isCloudBillMode()
      ? "Review source bill lines and OCI target mappings, then choose the OCI flex shape to price mapped usage."
      : "Review the rows, make adjustments, then choose the OCI flex shape to price.";
  }
}

function renderRateCard() {
  if (!els.rateCard || !els.rateCardShape) return;
  els.rateCard.innerHTML = "";
  const shape = selectedShape();
  els.rateCardShape.textContent = shape.label || "Selected shape";
  displayRateCard(state.rateCard).forEach((item) => {
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

function syncIntakeLayout() {
  const hasReviewData = state.rows.length > 0;
  els.intakePage.classList.toggle("has-review", hasReviewData);
  els.pricingRail.classList.toggle("is-hidden", !hasReviewData);
}

function setUploadLoading(isLoading, fileName = "") {
  els.uploadPanel.classList.toggle("is-uploading", isLoading);
  els.uploadProgress.classList.toggle("is-hidden", !isLoading);
  els.fileInput.disabled = isLoading;
  if (isLoading) {
    els.uploadStatus.textContent = "";
    els.uploadStatus.style.color = "var(--muted)";
    els.uploadProgressDetail.textContent = fileName
      ? isCloudBillMode()
        ? `Parsing ${fileName}, detecting ${providerLabel().toLowerCase()} provider signals, and mapping bill-line meters to OCI services.`
        : `Parsing ${fileName}, finding the inventory table, and cleaning CPU, RAM, storage, OS, and environment fields.`
      : "Reading workbook sheets and normalizing server inventory fields.";
  }
}

function setTableEditStatus(message = "", tone = "") {
  if (!els.tableEditStatus) return;
  els.tableEditStatus.textContent = message;
  els.tableEditStatus.className = "table-assistant-status";
  if (tone) {
    els.tableEditStatus.classList.add(`is-${tone}`);
  }
}

function setTableEditLoading(isLoading) {
  if (!els.applyTableEdit || !els.tableEditPrompt) return;
  els.applyTableEdit.disabled = isLoading;
  els.tableEditPrompt.disabled = isLoading;
  els.applyTableEdit.textContent = isLoading ? "Applying..." : "Apply changes";
}

function resetPricingAfterTableChange(statusText = "Table updated") {
  state.pricing = null;
  state.ramp.signature = "";
  els.engineStatus.textContent = statusText;
  els.pricingSummary.className = "empty-state";
  els.pricingSummary.textContent = state.fullServiceBeta
    ? "Review the updated source service rows, then choose the OCI flex shape to price."
    : "Review the updated rows, then choose the OCI flex shape to price.";
}

function renderShapeChoices() {
  if (!els.shapeGrid) return;
  const shapes = shapesForVendor();
  renderShapeVendorMeta();
  if (!shapes.length) {
    els.shapeGrid.innerHTML = `<div class="shape-empty-state">No ${escapeHtml(vendorDefinition().label)} shapes are currently available.</div>`;
    return;
  }
  els.shapeGrid.innerHTML = shapes
    .map((shape) => {
      const isSelected = shape.key === state.selectedShape;
      return `
        <button
          id="shape-tab-${escapeHtml(shape.key)}"
          class="shape-tab ${isSelected ? "is-selected" : ""}"
          type="button"
          role="tab"
          aria-selected="${isSelected ? "true" : "false"}"
          aria-controls="shapeRatePanel"
          data-shape="${escapeHtml(shape.key)}"
          style="--shape-accent:${escapeHtml(shape.accent || "#c74634")}"
        >
          <span class="shape-tab-name">${escapeHtml(shape.shortLabel || shape.label)}</span>
          <span class="shape-tab-meta">${escapeHtml(shape.family || "OCI shape")}</span>
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
  els.shapeFamily.textContent = shape.family || "OCI flex shape";
  els.shapeDetailTitle.textContent = shape.label || "Selected shape";
  els.shapeDetailSummary.textContent = shape.summary || "Selected shape rates will be applied to approved rows.";
  if (els.shapeDetailRates) {
    els.shapeDetailRates.innerHTML = `
      <table class="shape-rate-card-table">
        <thead>
          <tr>
            <th>Item</th>
            <th>SKU</th>
            <th>Value</th>
            <th>Unit</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Compute</td>
            <td>${escapeHtml(shape.computeSku || "Compute")}</td>
            <td>$${Number(shape.computeRate || 0).toFixed(4)}</td>
            <td>OCPU/hr</td>
          </tr>
          <tr>
            <td>Memory</td>
            <td>${escapeHtml(shape.memorySku || "Memory")}</td>
            <td>$${Number(shape.memoryRate || 0).toFixed(4)}</td>
            <td>GB/hr</td>
          </tr>
          <tr>
            <td>Billing month</td>
            <td>-</td>
            <td>${formatNumber(shape.hoursPerMonth || 730)}</td>
            <td>hrs/mo</td>
          </tr>
        </tbody>
      </table>
    `;
  }
}

function renderStats(meta = {}) {
  const fields = previewFields();
  const visibleRows = reviewRowEntries(fields).length;
  const approved = state.rows.filter((row) => row.__approved !== false).length;
  els.rowCount.textContent = state.showMissingOnly
    ? `${formatNumber(visibleRows)} / ${formatNumber(state.rows.length)}`
    : meta.rowCount ?? state.rows.length;
  els.columnCount.textContent = fields.length;
  els.approvedCount.textContent = approved;
  els.sheetName.textContent = meta.sheetName || els.sheetName.textContent || "-";
  syncMissingFilterUi(fields);
}

function renderTable() {
  const fields = previewFields();
  const rowEntries = reviewRowEntries(fields);
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  headRow.append(headerCell("Approve"));
  fields.forEach((field) => headRow.append(headerCell(field.label)));
  thead.append(headRow);

  const tbody = document.createElement("tbody");
  rowEntries.forEach(({ row, rowIndex }) => {
    const tr = document.createElement("tr");
    tr.dataset.rowIndex = String(rowIndex);
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
      td.dataset.rowIndex = String(rowIndex);
      td.dataset.fieldKey = field.key;
      td.classList.toggle("is-missing-data", !hasCellContent(row[field.key]));
      const cellEditor = document.createElement("div");
      cellEditor.className = "cell-editor";
      const input = document.createElement("input");
      input.type = "text";
      input.value = row[field.key] ?? "";
      input.placeholder = hasCellContent(row[field.key]) ? "" : "Missing data";
      input.dataset.rowIndex = String(rowIndex);
      input.dataset.fieldKey = field.key;
      input.setAttribute("aria-label", `${field.label}, row ${rowIndex + 1}`);
      input.addEventListener("input", () => {
        row[field.key] = input.value;
        const isMissing = !hasCellContent(input.value);
        td.classList.toggle("is-missing-data", isMissing);
        input.placeholder = isMissing ? "Missing data" : "";
        syncMissingFilterUi(fields);
      });
      input.addEventListener("blur", () => {
        if (state.showMissingOnly && !rowHasMissingData(row, fields)) {
          renderTable();
        }
      });
      const fillHandle = document.createElement("button");
      fillHandle.className = "fill-handle";
      fillHandle.type = "button";
      fillHandle.dataset.rowIndex = String(rowIndex);
      fillHandle.dataset.fieldKey = field.key;
      fillHandle.setAttribute("aria-label", `Drag to fill ${field.label} down from row ${rowIndex + 1}`);
      fillHandle.addEventListener("pointerdown", startCellFill);
      cellEditor.append(input, fillHandle);
      td.append(cellEditor);
      tr.append(td);
    });
    tbody.append(tr);
  });

  if (!rowEntries.length) {
    const emptyRow = document.createElement("tr");
    emptyRow.className = "table-empty-row";
    const emptyCell = document.createElement("td");
    emptyCell.colSpan = fields.length + 1;
    emptyCell.textContent = fields.length
      ? "No rows are missing data in the visible fields."
      : "No visible fields to check for missing data.";
    emptyRow.append(emptyCell);
    tbody.append(emptyRow);
  }

  els.reviewTable.replaceChildren(thead, tbody);
  renderStats();
}

function focusReviewField(fieldKey) {
  window.requestAnimationFrame(() => {
    const wrap = els.reviewTable.closest(".table-wrap");
    const input = [...els.reviewTable.querySelectorAll("input[data-field-key]")].find(
      (item) => item.dataset.fieldKey === fieldKey,
    );
    const cell = input?.closest("td");
    if (!wrap || !input || !cell) return;
    wrap.scrollLeft = Math.max(0, cell.offsetLeft - 92);
    input.focus();
  });
}

function headerCell(label) {
  const th = document.createElement("th");
  th.scope = "col";
  th.textContent = label;
  if (label.toLowerCase().includes("ocpu")) {
    th.title = "Uploaded spreadsheet CPU values are assumed to be vCPUs and converted using 2 vCPUs = 1 OCPU.";
  }
  return th;
}

function clearFillPreview() {
  els.reviewTable.querySelectorAll(".is-fill-preview").forEach((cell) => {
    cell.classList.remove("is-fill-preview");
  });
}

function fillTargetRowIndex(event) {
  const target = document.elementFromPoint(event.clientX, event.clientY);
  const row = target?.closest?.("tr[data-row-index]");
  if (!row) return activeFill?.endRowIndex ?? activeFill?.startRowIndex ?? 0;
  const rowIndex = Number(row.dataset.rowIndex);
  return Number.isFinite(rowIndex) ? rowIndex : activeFill?.startRowIndex ?? 0;
}

function scrollTableDuringFill(event) {
  const wrap = els.reviewTable.closest(".table-wrap");
  if (!wrap) return;
  const rect = wrap.getBoundingClientRect();
  if (event.clientY > rect.bottom - 28) {
    wrap.scrollTop += 18;
  } else if (event.clientY < rect.top + 28) {
    wrap.scrollTop -= 18;
  }
}

function updateFillPreview(rowIndex) {
  if (!activeFill) return;
  clearFillPreview();
  const endRowIndex = Math.max(activeFill.startRowIndex, Math.min(rowIndex, state.rows.length - 1));
  activeFill.endRowIndex = endRowIndex;
  els.reviewTable.querySelectorAll("td[data-row-index][data-field-key]").forEach((cell) => {
    const cellRow = Number(cell.dataset.rowIndex);
    if (cell.dataset.fieldKey === activeFill.fieldKey && cellRow > activeFill.startRowIndex && cellRow <= endRowIndex) {
      cell.classList.add("is-fill-preview");
    }
  });
}

function moveCellFill(event) {
  if (!activeFill) return;
  event.preventDefault();
  scrollTableDuringFill(event);
  updateFillPreview(fillTargetRowIndex(event));
}

function endCellFill(event) {
  if (!activeFill) return;
  event.preventDefault();
  updateFillPreview(fillTargetRowIndex(event));
  document.removeEventListener("pointermove", moveCellFill);
  document.removeEventListener("pointerup", endCellFill);
  document.removeEventListener("pointercancel", cancelCellFill);
  document.body.classList.remove("is-fill-dragging");

  const { startRowIndex, endRowIndex, fieldKey, value, handle, pointerId } = activeFill;
  const rowsToFill = Math.max(0, endRowIndex - startRowIndex);
  if (handle?.releasePointerCapture && pointerId !== undefined) {
    try {
      handle.releasePointerCapture(pointerId);
    } catch {
      // Pointer capture may already be released by the browser.
    }
  }
  activeFill = null;
  clearFillPreview();

  if (!rowsToFill) return;
  if (!hasCellContent(value)) {
    setTableEditStatus("Enter a value before dragging the fill handle.", "warning");
    return;
  }

  for (let rowIndex = startRowIndex + 1; rowIndex <= endRowIndex; rowIndex += 1) {
    state.rows[rowIndex][fieldKey] = value;
  }
  renderTable();
  resetPricingAfterTableChange("Table filled down");
  setTableEditStatus(`Copied "${value}" to ${rowsToFill} row${rowsToFill === 1 ? "" : "s"}.`, "success");
}

function cancelCellFill() {
  const { handle, pointerId } = activeFill || {};
  document.removeEventListener("pointermove", moveCellFill);
  document.removeEventListener("pointerup", endCellFill);
  document.removeEventListener("pointercancel", cancelCellFill);
  document.body.classList.remove("is-fill-dragging");
  if (handle?.releasePointerCapture && pointerId !== undefined) {
    try {
      handle.releasePointerCapture(pointerId);
    } catch {
      // Pointer capture may already be released by the browser.
    }
  }
  activeFill = null;
  clearFillPreview();
}

function startCellFill(event) {
  event.preventDefault();
  event.stopPropagation();
  const handle = event.currentTarget;
  const startRowIndex = Number(handle.dataset.rowIndex);
  const fieldKey = handle.dataset.fieldKey;
  const input = handle.parentElement?.querySelector("input");
  if (!fieldKey || !Number.isFinite(startRowIndex) || !input) return;

  activeFill = {
    fieldKey,
    startRowIndex,
    endRowIndex: startRowIndex,
    value: input.value,
    handle,
    pointerId: event.pointerId,
  };
  if (handle.setPointerCapture) {
    try {
      handle.setPointerCapture(event.pointerId);
    } catch {
      // Pointer capture is an enhancement; drag-fill still works without it.
    }
  }
  document.body.classList.add("is-fill-dragging");
  document.addEventListener("pointermove", moveCellFill);
  document.addEventListener("pointerup", endCellFill);
  document.addEventListener("pointercancel", cancelCellFill);
}

async function uploadFile(file) {
  if (!file) return;
  setUploadLoading(true, file.name);
  const body = new FormData();
  body.append("file", file);
  body.append("intakeMode", state.intakeMode);
  body.append("providerHint", state.providerHint);
  body.append("fullServiceBeta", state.fullServiceBeta ? "true" : "false");

  try {
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
    state.fullServiceCatalog = payload.fullServiceCatalog || state.fullServiceCatalog;
    state.selectedShape = payload.selectedShape?.key || state.selectedShape;
    state.rateCard = selectedShape().rateCard || payload.rateCard || [];
    syncVendorForSelectedShape();
    state.uploadMetadata = payload.metadata || {};
    state.intakeMode = payload.metadata?.intakeMode || state.intakeMode;
    state.fullServiceBeta = state.intakeMode === "cloud_bill";
    state.showMissingOnly = false;
    state.pricing = null;
    syncModeUi();

    els.uploadStatus.textContent = "";
    showIntakePage();
    els.uploadPanel.classList.add("is-hidden");
    els.reviewPanel.classList.remove("is-hidden");
    const parserLabel =
      payload.metadata?.parser === "llm-assisted"
        ? "OpenAI normalized"
        : payload.metadata?.parser === "cloud-bill-adapter"
          ? "Cloud bill parser"
          : payload.metadata?.parser === "cloud-bill-pdf"
            ? "PDF bill parser"
          : "Rule-based parse";
    const detectedProvider = payload.metadata?.detectedProvider;
    const modeLabel = isCloudBillMode()
      ? ` • ${detectedProvider || providerLabel()} cloud bill`
      : "";
    const grain = payload.metadata?.serverGrain && payload.metadata.serverGrain !== "unknown" ? ` • ${payload.metadata.serverGrain} grain` : "";
    els.sheetMeta.textContent = payload.fileName;
    els.sheetMeta.title = `Sheet "${payload.sheetName}" • ${parserLabel}${modeLabel}${grain} • data begins on row ${payload.metadata.dataStartRow}`;
    els.sheetName.textContent = payload.sheetName;
    renderRateCard();
    renderProcessorPicker();
    renderShapeChoices();
    renderShapeDetail();
    renderTable();
    syncIntakeLayout();
    setStep("review");
    els.engineStatus.textContent = isCloudBillMode()
      ? `${detectedProvider || providerLabel()} bill upload`
      : payload.metadata?.parser === "llm-assisted"
        ? "OpenAI normalized upload"
        : "Ready for approval";
    els.pricingSummary.className = "empty-state";
    const notes = payload.metadata?.extractionNotes || [];
    const warning = payload.llmWarning ? `${payload.llmWarning} ` : "";
    els.pricingSummary.textContent =
      warning ||
      (isCloudBillMode()
        ? `${formatNumber(payload.metadata?.mappedCount || 0)} bill lines mapped to OCI products; ${formatNumber(payload.metadata?.unmappedCount || 0)} lines need review before they affect the OCI total.`
        : notes.length
        ? `Review the normalized rows. ${notes.slice(0, 2).join(" ")}`
        : "Review the rows, make adjustments, then choose the OCI flex shape to price.");
  } finally {
    setUploadLoading(false);
  }
}

function setUploadingError(error) {
  els.uploadStatus.textContent = error.message;
  els.uploadStatus.style.color = "var(--danger)";
}

function makeBlankRow(prefix = "manual") {
  const row = {
    __id: `${prefix}-${Date.now()}-${state.rows.length + 1}`,
    __sourceRow: "manual",
    __approved: true,
  };
  state.fields.forEach((field) => {
    row[field.key] = "";
  });
  return row;
}

function initializeManualReviewTable() {
  state.intakeMode = "on_prem";
  state.providerHint = "auto";
  state.fullServiceBeta = false;
  state.fields = MANUAL_REVIEW_FIELDS.map((field) => ({
    ...field,
    sourceColumn: null,
    important: true,
    manual: true,
  }));
  state.rows = [makeBlankRow("manual-entry")];
  state.uploadMetadata = {
    parser: "manual-entry",
    rowCount: state.rows.length,
    sheetName: "Manual entry",
  };
  state.showMissingOnly = false;
  state.pricing = null;
  state.ramp.signature = "";
  syncModeUi();
  els.fileInput.value = "";
  els.uploadStatus.textContent = "";
  els.sheetMeta.textContent = "Manual entry";
  els.sheetMeta.title = "Blank table for manual entry.";
  els.sheetName.textContent = "Manual entry";
  renderRateCard();
  renderProcessorPicker();
  renderShapeChoices();
  renderShapeDetail();
  renderTable();
  syncIntakeLayout();
  els.engineStatus.textContent = "Manual entry";
  els.pricingSummary.className = "empty-state";
  els.pricingSummary.textContent = "Fill in one or more rows, then choose the OCI flex shape to price.";
  setTableEditStatus("Blank table ready. Add rows or columns as needed.", "success");
}

function ensureReviewRows() {
  if (!state.rows.length) {
    initializeManualReviewTable();
  }
}

function addBlankRow() {
  if (!state.fields.length) {
    initializeManualReviewTable();
    return;
  }
  state.rows.push(makeBlankRow());
  renderTable();
  resetPricingAfterTableChange("Manual row added");
}

function showAddColumnForm() {
  if (!els.addColumnForm || !els.newColumnName) return;
  els.addColumnForm.classList.remove("is-hidden");
  els.newColumnName.focus();
}

function hideAddColumnForm() {
  if (!els.addColumnForm || !els.newColumnName) return;
  els.addColumnForm.classList.add("is-hidden");
  els.newColumnName.value = "";
}

function addManualColumn(label) {
  const cleanLabel = String(label || "").trim();
  if (!state.rows.length) {
    setTableEditStatus("Upload a workbook or bill first.", "error");
    return;
  }
  if (!cleanLabel) {
    setTableEditStatus("Name the new column first.", "error");
    els.newColumnName?.focus();
    return;
  }

  let field = state.fields.find((item) => normalizeText(item.label) === normalizeText(cleanLabel));
  const wasExisting = Boolean(field);
  if (!field) {
    field = {
      key: uniqueFieldKey(cleanLabel),
      label: cleanLabel,
      sourceColumn: null,
      manual: true,
      userAdded: true,
    };
    state.fields.push(field);
  } else {
    field.manual = true;
    field.userAdded = true;
  }

  state.rows.forEach((row) => {
    if (!(field.key in row)) {
      row[field.key] = "";
    }
  });

  renderTable();
  resetPricingAfterTableChange(wasExisting ? "Column revealed" : "Manual column added");
  setTableEditStatus(`${field.label} column ${wasExisting ? "is now visible" : "added"}.`, "success");
  hideAddColumnForm();
  focusReviewField(field.key);
}

function submitAddColumn(event) {
  event.preventDefault();
  addManualColumn(els.newColumnName?.value);
}

async function applyTableEdit() {
  const instruction = els.tableEditPrompt.value.trim();
  if (!state.rows.length) {
    setTableEditStatus("Upload a workbook first.", "error");
    return;
  }
  if (!instruction) {
    setTableEditStatus("Describe the change first.", "error");
    els.tableEditPrompt.focus();
    return;
  }

  setTableEditLoading(true);
  setTableEditStatus("Applying table changes...");

  try {
    const { response, payload } = await fetchJson(
      "/api/edit-table",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          instruction,
          fields: state.fields,
          rows: state.rows,
          fullServiceBeta: state.fullServiceBeta,
        }),
      },
      90000,
    );
    if (!response.ok) {
      throw new Error(payload.error || "Table edit failed.");
    }

    state.rows = payload.rows || state.rows;
    renderTable();
    resetPricingAfterTableChange(state.openaiApiConnected ? "Table updated by OpenAI" : "Table updated");
    els.tableEditPrompt.value = "";

    const warnings = Array.isArray(payload.warnings) ? payload.warnings.filter(Boolean) : [];
    const summary = payload.summary || `Applied ${payload.appliedChanges?.length || 0} table update(s).`;
    setTableEditStatus([summary, ...warnings.slice(0, 2)].join(" "), warnings.length ? "warning" : "success");
  } catch (error) {
    setTableEditStatus(error.message, "error");
  } finally {
    setTableEditLoading(false);
  }
}

async function priceRows() {
  els.priceButton.disabled = true;
  els.priceButton.textContent = "Pricing...";
  els.priceShapeButton.disabled = true;
  els.priceShapeButton.textContent = "Pricing...";
  els.rerunPricing.disabled = true;
  els.rerunPricing.textContent = "Pricing...";
  els.engineStatus.textContent = isCloudBillMode()
    ? `Mapping cloud bill lines to OCI equivalents for ${selectedShape().label}`
    : `Mapping SKUs for ${selectedShape().label}`;

  try {
    const { response, payload } = await fetchJson(
      "/api/price",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          fields: state.fields,
          rows: state.rows,
          shape: state.selectedShape,
          intakeMode: state.intakeMode,
          providerHint: state.providerHint,
          fullServiceBeta: state.fullServiceBeta,
          bomMatch: state.bomMatch,
          hideGpuPricing: state.hideGpuPricing,
          hideWindowsPricing: state.hideWindowsPricing,
          rightsize: state.rightsize,
        }),
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
    els.priceShapeButton.textContent = pricingActionLabel("price");
    els.rerunPricing.disabled = false;
    els.rerunPricing.textContent = pricingActionLabel("rerun");
  }
}

async function exportToExcel() {
  if (!state.pricing) return;
  const button = els.exportExcel;
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Exporting...";
  try {
    const monthly = (typeof rampMonthlyValues === "function" && state.ramp.points.length)
      ? rampMonthlyValues()
      : [];
    const ramp = { ceiling: state.ramp.ceiling, monthly };
    const response = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        fields: state.fields,
        rows: state.rows,
        shape: state.selectedShape,
        intakeMode: state.intakeMode,
        fullServiceBeta: state.fullServiceBeta,
        bomMatch: state.bomMatch,
        hideGpuPricing: state.hideGpuPricing,
        hideWindowsPricing: state.hideWindowsPricing,
        rightsize: state.rightsize,
        ramp,
        existingInfraCost: state.existingInfraCost || 0,
      }),
    });
    if (!response.ok) {
      let message = "Export failed.";
      try {
        message = (await response.json()).error || message;
      } catch (err) {
        /* non-JSON error body */
      }
      throw new Error(message);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "OCI_BOM_Export.xlsx";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    els.engineStatus.textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

function renderPricing(pricing) {
  const shape = pricing.selectedShape || selectedShape();
  const cloudBill = pricing.intakeMode === "cloud_bill" || pricing.cloudBillMode;
  const modeLabel = cloudBill ? "Cloud bill" : pricing.fullServiceBeta ? "Full service" : shape.label;
  els.engineStatus.textContent = `${modeLabel}: ${pricing.engine === "llm-assisted" ? "OpenAI-assisted" : "Local mapping"}`;
  els.pricingSummary.className = "pricing-result";

  const warning = pricing.llmWarning ? `<p class="warning">${pricing.llmWarning}</p>` : "";
  const rows = pricing.rows
    .slice()
    .sort((a, b) => b.monthly - a.monthly)
    .slice(0, 10)
    .map(
      (row) => `
        <tr>
          <td>${escapeHtml(fallbackEntityName(row))}</td>
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
      ${
        cloudBill
          ? `<div class="kpi"><span>Mapped lines</span><strong>${formatNumber(pricing.totals.mappedServiceRows)}</strong></div>
             <div class="kpi"><span>Needs review</span><strong>${formatNumber(pricing.totals.unpricedServiceRows)}</strong></div>`
          : pricing.fullServiceBeta
          ? `<div class="kpi"><span>Mapped services</span><strong>${formatNumber(pricing.totals.mappedServiceRows)}</strong></div>
             <div class="kpi"><span>Review rows</span><strong>${formatNumber(pricing.totals.unpricedServiceRows)}</strong></div>`
          : `<div class="kpi"><span>OCPUs</span><strong>${formatNumber(pricing.totals.ocpus)}</strong></div>
             <div class="kpi"><span>Shape</span><strong>${escapeHtml(shape.shortLabel || shape.label)}</strong></div>`
      }
    </div>
    <table class="result-table">
      <thead>
        <tr><th>${cloudBill ? "Source line" : "Application"}</th><th>${cloudBill ? "Context" : "Env"}</th><th>Monthly</th></tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function showIntakePage() {
  els.intakePage.classList.remove("is-hidden");
  els.shapePage.classList.add("is-hidden");
  els.resultsPage.classList.add("is-hidden");
  syncIntakeLayout();
  if (state.rows.length) {
    els.uploadPanel.classList.add("is-hidden");
    els.reviewPanel.classList.remove("is-hidden");
    setStep("review");
  } else {
    els.uploadPanel.classList.remove("is-hidden");
    els.reviewPanel.classList.add("is-hidden");
    setStep("upload");
  }
}

function showUploadPage() {
  els.intakePage.classList.remove("is-hidden");
  els.shapePage.classList.add("is-hidden");
  els.resultsPage.classList.add("is-hidden");
  els.uploadPanel.classList.remove("is-hidden");
  els.reviewPanel.classList.add("is-hidden");
  syncIntakeLayout();
  setStep("upload");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showReviewPage() {
  ensureReviewRows();
  els.intakePage.classList.remove("is-hidden");
  els.shapePage.classList.add("is-hidden");
  els.resultsPage.classList.add("is-hidden");
  els.uploadPanel.classList.add("is-hidden");
  els.reviewPanel.classList.remove("is-hidden");
  renderTable();
  syncIntakeLayout();
  setStep("review");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showShapePage() {
  if (!state.rows.length) {
    showReviewPage();
    return;
  }
  els.intakePage.classList.add("is-hidden");
  els.shapePage.classList.remove("is-hidden");
  els.resultsPage.classList.add("is-hidden");
  renderProcessorPicker();
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

function navigateStep(step) {
  if (step === "upload") {
    showUploadPage();
    return;
  }
  if (step === "review") {
    showReviewPage();
    return;
  }
  if (step === "shape") {
    showShapePage();
    return;
  }
  if (step === "price") {
    if (state.pricing) {
      showResultsPage();
    } else if (state.rows.length) {
      showShapePage();
    } else {
      showReviewPage();
    }
  }
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

const RAMP_CHART = {
  width: 760,
  height: 330,
  pad: { top: 30, right: 34, bottom: 48, left: 78 },
};

const RAMP_CHART_COMPACT = {
  width: 430,
  height: 300,
  pad: { top: 28, right: 22, bottom: 42, left: 58 },
  compact: true,
};

let rampDragPointerId = null;
let rampDragPointId = null;

function currentRampChartConfig() {
  const width = els.rampChart?.getBoundingClientRect().width || RAMP_CHART.width;
  return width < 560 ? RAMP_CHART_COMPACT : RAMP_CHART;
}

function formatCompactCurrency(value) {
  const number = Number(value || 0);
  const abs = Math.abs(number);
  if (abs >= 1000000) {
    const amount = number / 1000000;
    return `$${amount >= 10 ? amount.toFixed(0) : amount.toFixed(1)}M`;
  }
  if (abs >= 1000) {
    const amount = number / 1000;
    return `$${amount >= 10 ? amount.toFixed(0) : amount.toFixed(1)}K`;
  }
  return `$${Math.round(number)}`;
}

function newRampPoint(month, monthly) {
  const pointMonth = Math.round(clamp(month, 1, state.ramp.months));
  const point = {
    id: `ramp-point-${state.ramp.nextPointId}`,
    month: pointMonth,
    monthly: clampRampMonthly("", pointMonth, monthly),
  };
  state.ramp.nextPointId += 1;
  return point;
}

function rampPointNeighbors(pointId, month) {
  const targetMonth = Math.round(clamp(month, 1, state.ramp.months));
  const others = state.ramp.points
    .filter((point) => point.id !== pointId)
    .map((point) => ({
      ...point,
      month: Math.round(clamp(point.month, 1, state.ramp.months)),
      monthly: clamp(point.monthly, 0, state.ramp.ceiling),
    }))
    .sort((a, b) => a.month - b.month || a.id.localeCompare(b.id));
  let previous = { id: "ramp-origin", month: 0, monthly: 0 };
  let next = null;
  for (const point of others) {
    if (point.month <= targetMonth) {
      previous = point;
    } else {
      next = point;
      break;
    }
  }
  return { previous, next };
}

function clampRampMonthly(pointId, month, monthly) {
  const { previous, next } = rampPointNeighbors(pointId, month);
  return clamp(monthly, previous.monthly, next?.monthly ?? state.ramp.ceiling);
}

function sortedRampPoints(includeOrigin = true) {
  const points = state.ramp.points
    .map((point) => ({
      ...point,
      month: Math.round(clamp(point.month, 1, state.ramp.months)),
      monthly: clamp(point.monthly, 0, state.ramp.ceiling),
    }))
    .sort((a, b) => a.month - b.month || a.id.localeCompare(b.id));
  return includeOrigin ? [{ id: "ramp-origin", month: 0, monthly: 0, fixed: true }, ...points] : points;
}

function selectedRampPoint() {
  return (
    state.ramp.points.find((point) => point.id === state.ramp.selectedPointId) ||
    sortedRampPoints(false)[state.ramp.points.length - 1] ||
    null
  );
}

function selectRampPoint(pointId) {
  if (state.ramp.points.some((point) => point.id === pointId)) {
    state.ramp.selectedPointId = pointId;
  }
}

function setRampPoint(pointId, month, monthly) {
  const point = state.ramp.points.find((item) => item.id === pointId);
  if (!point) return;
  const pointMonth = Math.round(clamp(month, 1, state.ramp.months));
  point.month = pointMonth;
  point.monthly = clampRampMonthly(point.id, pointMonth, monthly);
  state.ramp.selectedPointId = point.id;
  renderConsumptionRamp();
}

function rampValueAtMonth(month) {
  const points = sortedRampPoints(true);
  const targetMonth = clamp(month, 0, state.ramp.months);
  for (let index = 1; index < points.length; index += 1) {
    const prev = points[index - 1];
    const next = points[index];
    if (targetMonth <= next.month) {
      const span = Math.max(1, next.month - prev.month);
      const progress = (targetMonth - prev.month) / span;
      return prev.monthly + (next.monthly - prev.monthly) * progress;
    }
  }
  return points[points.length - 1]?.monthly || 0;
}

function addRampPoint(month, monthly) {
  if (state.ramp.points.length >= 8) return selectedRampPoint();
  const point = newRampPoint(month, monthly);
  state.ramp.points.push(point);
  state.ramp.selectedPointId = point.id;
  renderConsumptionRamp();
  return point;
}

function addRampPointInLargestGap() {
  const points = sortedRampPoints(true);
  let bestStart = points[0];
  let bestEnd = points[1] || { month: state.ramp.months, monthly: state.ramp.ceiling };
  for (let index = 1; index < points.length; index += 1) {
    const start = points[index - 1];
    const end = points[index];
    if (end.month - start.month > bestEnd.month - bestStart.month) {
      bestStart = start;
      bestEnd = end;
    }
  }
  const month = Math.max(1, Math.round((bestStart.month + bestEnd.month) / 2));
  addRampPoint(month, rampValueAtMonth(month));
}

function removeSelectedRampPoint() {
  if (state.ramp.points.length <= 1) return;
  const selected = selectedRampPoint();
  if (!selected) return;
  state.ramp.points = state.ramp.points.filter((point) => point.id !== selected.id);
  state.ramp.selectedPointId = sortedRampPoints(false).at(-1)?.id || null;
  renderConsumptionRamp();
}

function rampMonthlyValues() {
  const values = [];
  for (let month = 1; month <= state.ramp.months; month += 1) {
    values.push(rampValueAtMonth(month));
  }
  return values;
}

function initializeConsumptionRamp(pricing) {
  const ceiling = Math.max(0, Number(pricing.totals?.monthly || 0));
  const shapeKey = pricing.selectedShape?.key || state.selectedShape;
  const signature = `${shapeKey}:${ceiling}:${pricing.rows.length}`;
  if (state.ramp.signature !== signature) {
    state.ramp.signature = signature;
    state.ramp.ceiling = ceiling;
    state.ramp.nextPointId = 1;
    state.ramp.points = [
      newRampPoint(12, ceiling * 0.35),
      newRampPoint(24, ceiling * 0.7),
      newRampPoint(36, ceiling),
    ];
    state.ramp.selectedPointId = state.ramp.points.at(-1).id;
  } else {
    state.ramp.ceiling = ceiling;
    state.ramp.points.forEach((point) => {
      point.month = Math.round(clamp(point.month, 1, state.ramp.months));
      point.monthly = clamp(point.monthly, 0, ceiling);
    });
  }
  renderConsumptionRamp();
}

function renderConsumptionRamp() {
  if (!els.rampChart) return;

  const ceiling = Math.max(0, Number(state.ramp.ceiling || 0));
  const months = state.ramp.months;
  const { width, height, pad, compact } = currentRampChartConfig();
  const innerWidth = width - pad.left - pad.right;
  const innerHeight = height - pad.top - pad.bottom;
  const baselineY = pad.top + innerHeight;
  const valueCeiling = Math.max(ceiling, 1);
  const xForMonth = (month) => pad.left + (clamp(month, 0, months) / months) * innerWidth;
  const yForValue = (value) => baselineY - (clamp(value, 0, valueCeiling) / valueCeiling) * innerHeight;
  const pathPoints = sortedRampPoints(true);
  const linePath = pathPoints
    .map((point, index) => `${index ? "L" : "M"} ${xForMonth(point.month).toFixed(2)} ${yForValue(point.monthly).toFixed(2)}`)
    .join(" ");
  const finalMonthly = pathPoints.at(-1)?.monthly || 0;
  const extendedPath = `${linePath} L ${xForMonth(months).toFixed(2)} ${yForValue(finalMonthly).toFixed(2)}`;
  const areaPath = `${extendedPath} L ${xForMonth(months).toFixed(2)} ${baselineY} L ${xForMonth(0).toFixed(2)} ${baselineY} Z`;
  const selected = selectedRampPoint();
  const selectedX = selected ? xForMonth(selected.month) : null;
  const selectedY = selected ? yForValue(selected.monthly) : null;
  const labelOnLeft = selectedX > width - (compact ? 145 : 230);
  const labelX = labelOnLeft ? selectedX - 14 : selectedX + 14;
  const labelY = selectedY == null ? 0 : Math.max(pad.top + 18, selectedY - 14);
  const labelAnchor = labelOnLeft ? "end" : "start";
  const yTicks = [0, 0.25, 0.5, 0.75, 1];
  const xTicks = [0, 12, 24, 36];

  els.rampChart.setAttribute("viewBox", `0 0 ${width} ${height}`);
  els.rampCeilingLabel.textContent = `BOM maximum ${formatCurrency(ceiling)}/mo`;
  els.rampPeakMonth.value = selected ? selected.month : "";
  els.rampPeakMonthly.max = ceiling.toFixed(2);
  els.rampPeakMonthly.value = selected ? selected.monthly.toFixed(2) : "";
  els.removeRampPoint.disabled = state.ramp.points.length <= 1;
  els.addRampPoint.disabled = state.ramp.points.length >= 8;

  const values = rampMonthlyValues();
  const total = values.reduce((sum, value) => sum + value, 0);
  const yearOne = values.slice(0, 12).reduce((sum, value) => sum + value, 0);
  const yearTwo = values.slice(12, 24).reduce((sum, value) => sum + value, 0);
  const yearThree = values.slice(24, 36).reduce((sum, value) => sum + value, 0);

  els.rampThreeYearTotal.textContent = formatCurrency(total);
  els.rampAvgMonthly.textContent = formatCurrency(total / months);
  [
    [els.rampYearOneTotal, yearOne],
    [els.rampYearTwoTotal, yearTwo],
    [els.rampYearThreeTotal, yearThree],
  ].forEach(([element, value]) => {
    element.textContent = formatCompactCurrency(value);
    element.title = formatCurrency(value);
  });

  const handleMarkup = sortedRampPoints(false)
    .map((point) => {
      const x = xForMonth(point.month);
      const y = yForValue(point.monthly);
      const selectedClass = point.id === state.ramp.selectedPointId ? " is-selected" : "";
      return `
        <circle class="ramp-handle-pulse${selectedClass}" cx="${x}" cy="${y}" r="16" data-ramp-point-id="${point.id}"></circle>
        <circle class="ramp-handle${selectedClass}" cx="${x}" cy="${y}" r="7" data-ramp-point-id="${point.id}"></circle>
      `;
    })
    .join("");

  els.rampChart.innerHTML = `
    <title id="rampChartTitle">Three year consumption ramp</title>
    <desc id="rampChartDesc">Drag any dot to shape the monthly spend ramp. Click the chart or use Add ramp dot to add another adjustable section.</desc>
    <rect class="ramp-plot-bg" x="${pad.left}" y="${pad.top}" width="${innerWidth}" height="${innerHeight}" rx="8"></rect>
    ${yTicks
      .map((tick) => {
        const y = yForValue(ceiling * tick);
        return `
          <line class="ramp-grid-line" x1="${pad.left}" y1="${y}" x2="${width - pad.right}" y2="${y}"></line>
          <text class="ramp-axis-label ramp-y-label" x="${pad.left - 12}" y="${y + 4}">${formatCompactCurrency(ceiling * tick)}</text>
        `;
      })
      .join("")}
    ${xTicks
      .map((month) => {
        const x = xForMonth(month);
        const anchor = month === 0 ? "start" : month === months ? "end" : "middle";
        return `
          <line class="ramp-grid-line ramp-grid-line-vertical" x1="${x}" y1="${pad.top}" x2="${x}" y2="${baselineY}"></line>
          <text class="ramp-axis-label" x="${x}" y="${height - 16}" text-anchor="${anchor}">${month} mo</text>
        `;
      })
      .join("")}
    <line class="ramp-ceiling-line" x1="${pad.left}" y1="${pad.top}" x2="${width - pad.right}" y2="${pad.top}"></line>
    <path class="ramp-area" d="${areaPath}"></path>
    <path class="ramp-line" d="${extendedPath}"></path>
    ${
      selected
        ? `<line class="ramp-peak-guide" x1="${selectedX}" y1="${selectedY}" x2="${selectedX}" y2="${baselineY}"></line>`
        : ""
    }
    ${handleMarkup}
    ${
      selected && !compact
        ? `<text class="ramp-peak-label" x="${labelX}" y="${labelY}" text-anchor="${labelAnchor}">
            ${formatCurrency(selected.monthly)}/mo in month ${selected.month}
          </text>`
        : ""
    }
  `;
}

function rampPointFromEvent(event) {
  const rect = els.rampChart.getBoundingClientRect();
  const { width, height } = currentRampChartConfig();
  return {
    x: ((event.clientX - rect.left) / rect.width) * width,
    y: ((event.clientY - rect.top) / rect.height) * height,
  };
}

function chartValueFromPointer(event) {
  if (!state.ramp.ceiling) return;
  const { pad, width, height } = currentRampChartConfig();
  const innerWidth = width - pad.left - pad.right;
  const innerHeight = height - pad.top - pad.bottom;
  const point = rampPointFromEvent(event);
  const month = Math.round(clamp(((point.x - pad.left) / innerWidth) * state.ramp.months, 1, state.ramp.months));
  const monthly = clamp(((pad.top + innerHeight - point.y) / innerHeight) * state.ramp.ceiling, 0, state.ramp.ceiling);
  return { month, monthly };
}

function updateRampFromPointer(event, pointId) {
  const value = chartValueFromPointer(event);
  if (!value) return;
  setRampPoint(pointId, value.month, value.monthly);
}

function startRampDrag(event) {
  if (!state.pricing) return;
  event.preventDefault();
  const targetHandle = event.target.closest?.("[data-ramp-point-id]");
  let pointId = targetHandle?.dataset.rampPointId;
  if (!pointId) {
    const value = chartValueFromPointer(event);
    if (!value) return;
    pointId = addRampPoint(value.month, value.monthly)?.id;
  }
  if (!pointId) return;
  selectRampPoint(pointId);
  rampDragPointId = pointId;
  rampDragPointerId = event.pointerId;
  els.rampChart.setPointerCapture?.(event.pointerId);
  els.rampChart.classList.add("is-dragging");
  updateRampFromPointer(event, pointId);
}

function moveRampDrag(event) {
  if (rampDragPointerId !== event.pointerId) return;
  event.preventDefault();
  updateRampFromPointer(event, rampDragPointId);
}

function endRampDrag(event) {
  if (rampDragPointerId !== event.pointerId) return;
  els.rampChart.releasePointerCapture?.(event.pointerId);
  rampDragPointerId = null;
  rampDragPointId = null;
  els.rampChart.classList.remove("is-dragging");
}

function nudgeRamp(event) {
  if (!state.pricing) return;
  const selected = selectedRampPoint();
  if (!selected) return;
  const monthlyStep = Math.max(state.ramp.ceiling * 0.05, 1);
  const handlers = {
    ArrowLeft: () => setRampPoint(selected.id, selected.month - 1, selected.monthly),
    ArrowRight: () => setRampPoint(selected.id, selected.month + 1, selected.monthly),
    ArrowDown: () => setRampPoint(selected.id, selected.month, selected.monthly - monthlyStep),
    ArrowUp: () => setRampPoint(selected.id, selected.month, selected.monthly + monthlyStep),
    Home: () => setRampPoint(selected.id, 1, selected.monthly),
    End: () => setRampPoint(selected.id, state.ramp.months, selected.monthly),
  };
  if (!handlers[event.key]) return;
  event.preventDefault();
  handlers[event.key]();
}

function resultKpiCard({ label, value, meta, accent = "#c74634", fill = 72, primary = false, title = "" }) {
  const safeFill = clamp(fill, 4, 100);
  const titleAttr = title ? ` title="${escapeHtml(title)}"` : "";
  return `
    <div class="result-kpi ${primary ? "primary" : ""}" style="--kpi-accent:${escapeHtml(accent)}; --kpi-fill:${safeFill}%"${titleAttr}>
      <div class="kpi-topline">
        <span>${escapeHtml(label)}</span>
      </div>
      <strong>${escapeHtml(value)}</strong>
      <em>${escapeHtml(meta)}</em>
      <div class="kpi-meter" aria-hidden="true"><b></b></div>
    </div>
  `;
}

function renderResults(pricing) {
  const topRows = pricing.rows.slice().sort((a, b) => b.monthly - a.monthly);
  const skuCosts = aggregateSkuCosts(pricing);
  const maxMonthly = topRows[0]?.monthly || 1;
  const engineLabel = pricing.engine === "llm-assisted" ? "OpenAI-assisted" : "local deterministic";
  const shape = pricing.selectedShape || selectedShape();
  const cloudBill = pricing.intakeMode === "cloud_bill" || pricing.cloudBillMode;
  const serviceRows = pricing.totals.mappedServiceRows || 0;
  const reviewRows = pricing.totals.unpricedServiceRows || 0;

  els.resultsShape.textContent = shape.label || "Selected shape";
  els.resultsSubtitle.textContent = cloudBill
    ? `${pricing.rows.length} source bill lines reviewed; ${serviceRows} mapped to OCI-equivalent products and ${reviewRows} need review before they affect totals.`
    : pricing.fullServiceBeta
    ? `${pricing.rows.length} approved items priced with OCI service mapping; ${serviceRows} service mappings priced and ${reviewRows} items need review.`
    : `${pricing.rows.length} approved workloads priced on ${shape.label} with ${engineLabel} SKU validation.`;
  els.topListHeading.textContent = cloudBill ? "Top source lines" : "Top workloads";
  els.detailHeading.textContent = cloudBill ? "Cloud bill mapping detail" : "Application cost detail";
  els.resultRowCount.textContent = cloudBill
    ? `${pricing.rows.length} source lines`
    : pricing.fullServiceBeta
      ? `${pricing.rows.length} priced items`
      : `${pricing.rows.length} workloads`;
  const totalRows = Math.max(1, pricing.rows.length);
  const mappedShare = (serviceRows / totalRows) * 100;
  const reviewShare = (reviewRows / totalRows) * 100;
  const monthlyScale = Math.min(100, Math.max(18, Math.log10(Math.max(10, pricing.totals.monthly || 0)) * 22));
  const computeScale = Math.min(100, Math.max(10, (pricing.totals.ocpus || serviceRows || 0) / Math.max(1, pricing.totals.ocpus || serviceRows || reviewRows || 1) * 100));
  const memoryScale = Math.min(100, Math.max(12, (pricing.totals.memoryGb || reviewRows || 0) / Math.max(1, pricing.totals.memoryGb || serviceRows || reviewRows || 1) * 100));
  const storageGb = Number(pricing.totals.blockStorageGb || 0) + Number(pricing.totals.fileStorageGb || 0);
  const storageScale = Math.min(100, Math.max(12, Math.log10(Math.max(10, storageGb || 0)) * 20));
  const pricingCards = `
    ${resultKpiCard({
      label: cloudBill ? "OCI-equivalent monthly" : "Monthly run rate",
      value: formatCompactCurrency(pricing.totals.monthly),
      meta: `${formatCompactCurrency(pricing.totals.annual)} annualized`,
      accent: "#c74634",
      fill: monthlyScale,
      primary: true,
      title: `${formatCurrency(pricing.totals.monthly)} monthly; ${formatCurrency(pricing.totals.annual)} annualized`,
    })}
    ${resultKpiCard({
      label: "Flex shape",
      value: shape.shortLabel || shape.label,
      meta: `$${Number(shape.computeRate || 0).toFixed(4)} OCPU/hr and $${Number(shape.memoryRate || 0).toFixed(4)} GB/hr`,
      accent: shape.accent || "#164f68",
      fill: 62,
    })}
    ${
      cloudBill
        ? `${resultKpiCard({
            label: "Mapped bill lines",
            value: formatNumber(serviceRows),
            meta: `${formatCurrency(pricing.totals.fullServiceMonthly)} from deterministic OCI rates`,
            accent: "#2f6f73",
            fill: mappedShare || 8,
          })}
          ${resultKpiCard({
            label: "Needs review",
            value: formatNumber(reviewRows),
            meta: `${formatCurrency(pricing.totals.unmappedSourceMonthlyCost)} source spend not in OCI total`,
            accent: reviewRows ? "#d97706" : "#067647",
            fill: reviewRows ? reviewShare : 100,
          })}`
      : pricing.fullServiceBeta
        ? `${resultKpiCard({
            label: "Mapped services",
            value: formatNumber(serviceRows),
            meta: `${formatCurrency(pricing.totals.fullServiceMonthly)} from service catalog rows`,
            accent: "#2f6f73",
            fill: mappedShare || 8,
          })}
          ${resultKpiCard({
            label: "Needs review",
            value: formatNumber(reviewRows),
            meta: "Recognized without usable OCI quantity",
            accent: reviewRows ? "#d97706" : "#067647",
            fill: reviewRows ? reviewShare : 100,
          })}`
        : ""
    }
  `;
  const specCards = `
    ${resultKpiCard({
      label: "Compute",
      value: formatKpiQuantity(pricing.totals.ocpus, "OCPUs"),
      meta: "Converted from spreadsheet vCPUs",
      accent: "#2f6f73",
      fill: computeScale,
      title: `${formatNumber(pricing.totals.ocpus)} OCPUs`,
    })}
    ${resultKpiCard({
      label: "Memory",
      value: formatKpiQuantity(pricing.totals.memoryGb, "GB"),
      meta: "GB-hours at 730 hrs/mo",
      accent: "#d4b483",
      fill: memoryScale,
      title: `${formatNumber(pricing.totals.memoryGb)} GB`,
    })}
    ${resultKpiCard({
      label: "Storage",
      value: formatKpiQuantity(storageGb, "GB"),
      meta: "Block + file storage",
      accent: "#7a5c1f",
      fill: storageScale,
      title: `${formatNumber(storageGb)} GB`,
    })}
  `;

  els.resultsKpis.innerHTML = `
    <section class="kpi-section" aria-label="Pricing summary">
      <div class="kpi-section-heading">
        <span>Pricing summary</span>
        <em>Calculated from approved rows</em>
      </div>
      <div class="kpi-row pricing-kpi-row">${pricingCards}</div>
    </section>
    <section class="kpi-section" aria-label="Specs identified">
      <div class="kpi-section-heading">
        <span>Specs identified</span>
        <em>Normalized from the uploaded table</em>
      </div>
      <div class="kpi-row specs-kpi-row">${specCards}</div>
    </section>
  `;

  initializeConsumptionRamp(pricing);
  renderCostMix(skuCosts, pricing.totals.monthly);
  renderTopWorkloads(topRows, maxMonthly, cloudBill);
  renderResultsTable(topRows, pricing.fullServiceBeta, cloudBill);
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
  const fullTotal = formatCurrency(total);
  const displayTotal = formatCompactCurrency(total);
  els.costDonut.style.background = `conic-gradient(${stops || "#dedbd3 0 100%"})`;
  els.costDonut.title = `${fullTotal}/mo`;
  els.costDonut.setAttribute("aria-label", `Cost mix chart, ${fullTotal} per month`);
  els.costDonut.innerHTML = `<span title="${escapeHtml(`${fullTotal}/mo`)}"><strong>${escapeHtml(displayTotal)}</strong><em>/mo</em></span>`;
  els.costLegend.innerHTML = skuCosts
    .map((item, index) => {
      const color = colors[index % colors.length];
      const monthly = formatCurrency(item.monthly);
      return `
        <div class="legend-row" title="${escapeHtml(`${item.sku} - ${item.description}: ${monthly}`)}">
          <i style="background:${color}"></i>
          <span>${escapeHtml(item.sku)}</span>
          <strong>${monthly}</strong>
          <em>${escapeHtml(item.description)}</em>
        </div>
      `;
    })
    .join("");
}

function fallbackEntityName(row, noun = "Workload") {
  const rawName = String(row?.name || "").trim();
  if (rawName && !/^row-\d+$/i.test(rawName)) {
    return rawName;
  }
  const rowId = String(row?.rowId || "").trim();
  const sourceRow = String(row?.sourceRow || "").trim();
  const rowIdNumber = rowId.match(/^row-(\d+)$/i)?.[1];
  const suffix = /^\d+$/.test(sourceRow) ? sourceRow : rowIdNumber || "";
  return suffix ? `${noun} ${suffix}` : noun;
}

function cloudRowLabel(row) {
  const mapping = row.fullServiceMapping || {};
  return mapping.sourceService || fallbackEntityName(row, "Source line");
}

function cloudRowContext(row) {
  const mapping = row.fullServiceMapping || {};
  return [mapping.sourceProvider, mapping.sourceProduct, mapping.sourceRegion].filter(Boolean).join(" / ") || row.environment || "No source context";
}

function renderTopWorkloads(rows, maxMonthly, cloudBill = false) {
  els.topWorkloads.innerHTML = rows
    .slice(0, 8)
    .map((row) => {
      const width = Math.max(4, percent(row.monthly, maxMonthly));
      const label = cloudBill ? cloudRowLabel(row) : fallbackEntityName(row);
      const context = cloudBill ? cloudRowContext(row) : row.environment || "No environment";
      return `
        <div class="bar-row">
          <div class="bar-copy" title="${escapeHtml(label)}">
            <strong>${escapeHtml(label)}</strong>
            <span>${escapeHtml(context)}</span>
          </div>
          <div class="bar-track"><i style="width:${width}%"></i></div>
          <em>${formatCurrency(row.monthly)}</em>
        </div>
      `;
    })
    .join("");
}

function serviceSourceLabel(mapping) {
  if (!mapping) return "-";
  return [mapping.sourceProvider, mapping.sourceService || mapping.sourceProduct].filter(Boolean).join(" / ") || "-";
}

function serviceQuantityLabel(mapping, row) {
  if (mapping?.quantity) {
    return `${formatNumber(mapping.quantity)} ${mapping.unit || ""}`.trim();
  }
  const storage = Number(row.specs.blockStorageGb || 0) + Number(row.specs.fileStorageGb || 0);
  return storage ? `${formatNumber(storage)} GB` : "-";
}

function sortComparableValue(value) {
  if (value == null || value === "") {
    return { empty: true, value: "" };
  }
  if (typeof value === "number") {
    return { empty: !Number.isFinite(value), value };
  }
  const text = String(value).trim();
  return { empty: !text || text === "-", value: text.toLowerCase() };
}

function compareSortValues(left, right, direction = "asc") {
  const a = sortComparableValue(left);
  const b = sortComparableValue(right);
  if (a.empty && b.empty) return 0;
  if (a.empty) return 1;
  if (b.empty) return -1;
  const multiplier = direction === "asc" ? 1 : -1;
  if (typeof a.value === "number" && typeof b.value === "number") {
    return (a.value - b.value) * multiplier;
  }
  return String(a.value).localeCompare(String(b.value), undefined, {
    numeric: true,
    sensitivity: "base",
  }) * multiplier;
}

function activeResultSort(columns) {
  const requestedColumn = columns.find((column) => column.key === state.resultSort.key);
  const fallbackColumn = columns.find((column) => column.key === "monthly") || columns[0];
  const column = requestedColumn || fallbackColumn;
  const direction = requestedColumn
    ? state.resultSort.direction === "asc" ? "asc" : "desc"
    : column?.key === "monthly" ? "desc" : "asc";
  return { column, direction };
}

function sortResultRows(rows, columns) {
  const { column: activeColumn, direction } = activeResultSort(columns);
  if (!activeColumn) return rows.slice();
  return rows
    .map((row, index) => ({ row, index }))
    .sort((left, right) => {
      const comparison = compareSortValues(
        activeColumn.sortValue(left.row),
        activeColumn.sortValue(right.row),
        direction,
      );
      return comparison || left.index - right.index;
    })
    .map((item) => item.row);
}

function renderSortableHead(columns) {
  const { column: activeColumn, direction } = activeResultSort(columns);
  return `
    <thead>
      <tr>
        ${columns
          .map((column) => {
            const active = activeColumn?.key === column.key;
            const ariaSort = active ? (direction === "asc" ? "ascending" : "descending") : "none";
            return `
              <th class="${active ? `is-sorted is-${direction}` : "is-sortable"}" aria-sort="${ariaSort}">
                <button type="button" class="sort-header" data-result-sort="${escapeHtml(column.key)}">
                  <span>${escapeHtml(column.label)}</span>
                  <i aria-hidden="true"></i>
                </button>
              </th>
            `;
          })
          .join("")}
      </tr>
    </thead>
  `;
}

function renderResultTableFromColumns(rows, columns) {
  const sortedRows = sortResultRows(rows, columns);
  const body = sortedRows
    .map((row) => `
      <tr>
        ${columns.map((column) => `<td>${column.render(row)}</td>`).join("")}
      </tr>
    `)
    .join("");
  els.resultsTable.innerHTML = `${renderSortableHead(columns)}<tbody>${body}</tbody>`;
}

function sizeFlagBadge(row) {
  const check = row.sizeCheck || {};
  if (check.status === "impossible") {
    return ` <span class="size-flag size-flag-impossible" title="${escapeHtml(check.message || "")}">IMPOSSIBLE</span>`;
  }
  if (check.status === "baremetal") {
    return ` <span class="size-flag size-flag-baremetal" title="${escapeHtml(check.message || "")}">BARE METAL</span>`;
  }
  return "";
}

function renderResultsTable(rows, fullServiceBeta = false, cloudBill = false) {
  if (cloudBill) {
    const columns = [
      {
        key: "sourceService",
        label: "Source service",
        sortValue: (row) => row.fullServiceMapping?.sourceService || fallbackEntityName(row, "Source line"),
        render: (row) => escapeHtml(row.fullServiceMapping?.sourceService || fallbackEntityName(row, "Source line")),
      },
      {
        key: "sourceProduct",
        label: "Source SKU / meter",
        sortValue: (row) => row.fullServiceMapping?.sourceProduct || "",
        render: (row) => escapeHtml(row.fullServiceMapping?.sourceProduct || "-"),
      },
      {
        key: "ociTarget",
        label: "OCI target",
        sortValue: (row) => row.fullServiceMapping?.ociProduct || row.lineItems?.[0]?.description || "Needs review",
        render: (row) => escapeHtml(row.fullServiceMapping?.ociProduct || row.lineItems?.[0]?.description || "Needs review"),
      },
      {
        key: "usage",
        label: "Usage",
        sortValue: (row) => Number(row.fullServiceMapping?.quantity || row.specs?.blockStorageGb || row.specs?.fileStorageGb || 0),
        render: (row) => escapeHtml(serviceQuantityLabel(row.fullServiceMapping || {}, row)),
      },
      {
        key: "sourceCost",
        label: "Source cost",
        sortValue: (row) => Number(row.fullServiceMapping?.sourceMonthlyCost || 0),
        render: (row) => formatCurrency(row.fullServiceMapping?.sourceMonthlyCost || 0),
      },
      {
        key: "monthly",
        label: "OCI monthly",
        sortValue: (row) => Number(row.monthly || 0),
        render: (row) => formatCurrency(row.monthly),
      },
      {
        key: "status",
        label: "Status",
        sortValue: (row) => {
          const mapping = row.fullServiceMapping || {};
          return mapping.reviewRequired ? "Review" : mapping.confidence ? `${Math.round(mapping.confidence * 100)}% match` : "Unmapped";
        },
        render: (row) => {
        const mapping = row.fullServiceMapping || {};
        const status = mapping.reviewRequired
          ? "Review"
          : mapping.confidence
            ? `${Math.round(mapping.confidence * 100)}% match`
            : "Unmapped";
          return escapeHtml(status);
        },
      },
    ];
    renderResultTableFromColumns(rows, columns);
    return;
  }

  if (fullServiceBeta) {
    const columns = [
      {
        key: "workload",
        label: "Workload",
        sortValue: (row) => fallbackEntityName(row),
        render: (row) => escapeHtml(fallbackEntityName(row)),
      },
      {
        key: "source",
        label: "Source",
        sortValue: (row) => serviceSourceLabel(row.fullServiceMapping),
        render: (row) => escapeHtml(serviceSourceLabel(row.fullServiceMapping)),
      },
      {
        key: "ociProduct",
        label: "OCI product",
        sortValue: (row) => row.fullServiceMapping?.ociProduct || row.lineItems?.[0]?.description || "Needs review",
        render: (row) => escapeHtml(row.fullServiceMapping?.ociProduct || row.lineItems?.[0]?.description || "Needs review"),
      },
      {
        key: "quantity",
        label: "Quantity",
        sortValue: (row) => Number(row.fullServiceMapping?.quantity || row.specs?.blockStorageGb || row.specs?.fileStorageGb || 0),
        render: (row) => escapeHtml(serviceQuantityLabel(row.fullServiceMapping, row)),
      },
      {
        key: "monthly",
        label: "Monthly",
        sortValue: (row) => Number(row.monthly || 0),
        render: (row) => formatCurrency(row.monthly),
      },
      {
        key: "annual",
        label: "Annual",
        sortValue: (row) => Number(row.annual || 0),
        render: (row) => formatCurrency(row.annual),
      },
    ];
    renderResultTableFromColumns(rows, columns);
    return;
  }

  const columns = [
    {
      key: "workload",
      label: "Workload",
      sortValue: (row) => fallbackEntityName(row),
      render: (row) => escapeHtml(fallbackEntityName(row)) + sizeFlagBadge(row),
    },
    {
      key: "environment",
      label: "Env",
      sortValue: (row) => row.environment || "",
      render: (row) => escapeHtml(row.environment || "-"),
    },
    {
      key: "ocpus",
      label: "OCPUs",
      sortValue: (row) => Number(row.specs?.ocpus || 0),
      render: (row) => formatNumber(row.specs?.ocpus),
    },
    {
      key: "memory",
      label: "Memory",
      sortValue: (row) => Number(row.specs?.memoryGb || 0),
      render: (row) => `${formatNumber(row.specs?.memoryGb)} GB`,
    },
    {
      key: "storage",
      label: "Storage",
      sortValue: (row) => Number(row.specs?.blockStorageGb || 0) + Number(row.specs?.fileStorageGb || 0),
      render: (row) => `${formatNumber(Number(row.specs?.blockStorageGb || 0) + Number(row.specs?.fileStorageGb || 0))} GB`,
    },
    {
      key: "monthly",
      label: "Monthly",
      sortValue: (row) => Number(row.monthly || 0),
      render: (row) => formatCurrency(row.monthly),
    },
    {
      key: "annual",
      label: "Annual",
      sortValue: (row) => Number(row.annual || 0),
      render: (row) => formatCurrency(row.annual),
    },
  ];
  renderResultTableFromColumns(rows, columns);
}

if (els.resultsTable) {
  els.resultsTable.addEventListener("click", (event) => {
    const button = event.target.closest("[data-result-sort]");
    if (!button) return;
    const key = button.dataset.resultSort;
    const direction = state.resultSort.key === key && state.resultSort.direction === "asc" ? "desc" : "asc";
    state.resultSort = { key, direction };
    if (!state.pricing) return;
    renderResultsTable(
      state.pricing.rows || [],
      state.pricing.fullServiceBeta,
      state.pricing.intakeMode === "cloud_bill" || state.pricing.cloudBillMode,
    );
  });
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
els.addColumn?.addEventListener("click", showAddColumnForm);
els.addColumnForm?.addEventListener("submit", submitAddColumn);
els.cancelAddColumn?.addEventListener("click", hideAddColumnForm);
els.missingOnlyToggle?.addEventListener("change", () => {
  state.showMissingOnly = els.missingOnlyToggle.checked;
  renderTable();
  setTableEditStatus(
    state.showMissingOnly ? "Showing only rows with blank visible cells." : "Showing all review rows.",
    state.showMissingOnly ? "warning" : "success",
  );
});
els.applyTableEdit.addEventListener("click", applyTableEdit);
els.tableEditPrompt.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    event.preventDefault();
    applyTableEdit();
  }
});
els.priceButton.addEventListener("click", showShapePage);
els.priceShapeButton.addEventListener("click", priceRows);
els.rerunPricing.addEventListener("click", priceRows);
els.bomMatchToggle?.addEventListener("change", (event) => {
  state.bomMatch = event.target.checked;
});
els.hideGpuToggle?.addEventListener("change", (event) => {
  state.hideGpuPricing = event.target.checked;
});
els.hideWindowsToggle?.addEventListener("change", (event) => {
  state.hideWindowsPricing = event.target.checked;
});
els.rightsizeSwitch?.addEventListener("click", (event) => {
  const opt = event.target.closest("[data-rightsize]");
  if (!opt) return;
  state.rightsize = opt.dataset.rightsize === "true";
  els.rightsizeSwitch.querySelectorAll(".mode-opt").forEach((b) => {
    b.classList.toggle("is-active", b === opt);
  });
});
els.exportExcel?.addEventListener("click", exportToExcel);
els.backToReview.addEventListener("click", showIntakePage);
els.backToReviewFromShape.addEventListener("click", showIntakePage);
els.steps.forEach((step) => {
  step.addEventListener("click", () => navigateStep(step.dataset.step));
});
els.modeOnPrem?.addEventListener("click", () => setIntakeMode("on_prem"));
els.modeCloudBill?.addEventListener("click", () => setIntakeMode("cloud_bill"));
els.providerHint?.addEventListener("change", () => {
  state.providerHint = els.providerHint.value || "auto";
  syncModeUi();
});
syncModeUi();

if (els.rampChart) {
  els.rampChart.addEventListener("pointerdown", startRampDrag);
  els.rampChart.addEventListener("pointermove", moveRampDrag);
  els.rampChart.addEventListener("pointerup", endRampDrag);
  els.rampChart.addEventListener("pointercancel", endRampDrag);
  els.rampChart.addEventListener("keydown", nudgeRamp);
}

if (els.rampPeakMonth) {
  els.rampPeakMonth.addEventListener("input", () => {
    if (els.rampPeakMonth.value === "") return;
    const selected = selectedRampPoint();
    if (selected) {
      setRampPoint(selected.id, els.rampPeakMonth.value, selected.monthly);
    }
  });
}

if (els.rampPeakMonthly) {
  els.rampPeakMonthly.addEventListener("input", () => {
    if (els.rampPeakMonthly.value === "") return;
    const selected = selectedRampPoint();
    if (selected) {
      setRampPoint(selected.id, selected.month, els.rampPeakMonthly.value);
    }
  });
}

if (els.addRampPoint) {
  els.addRampPoint.addEventListener("click", addRampPointInLargestGap);
}

if (els.removeRampPoint) {
  els.removeRampPoint.addEventListener("click", removeSelectedRampPoint);
}

window.addEventListener("resize", () => {
  if (state.pricing) {
    renderConsumptionRamp();
  }
});

fetch("/api/health")
  .then((response) => response.json())
  .then((payload) => {
    state.rateCards = payload.rateCards || [];
    state.fullServiceCatalog = payload.fullServiceCatalog || [];
    state.openaiApiEnabled = Boolean(payload.openaiApiEnabled);
    state.openaiApiConfigured = Boolean(payload.openaiApiConfigured);
    state.openaiApiConnected = Boolean(payload.openaiApiConnected);
    state.openaiModel = payload.openaiModel || "";
    state.selectedShape = payload.selectedShape?.key || state.selectedShape;
    state.rateCard = selectedShape().rateCard || payload.rateCard || [];
    syncVendorForSelectedShape();
    syncApiUi();
    renderRateCard();
    renderProcessorPicker();
    renderShapeChoices();
    renderShapeDetail();
  })
  .catch(() => {
    els.engineStatus.textContent = "Backend unavailable";
  });
