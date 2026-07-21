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
  hideGpuPricing: false,
  hideWindowsPricing: false,
  rightsize: false,
  auto: false,
  cpuUnit: "auto",
  hoursPerMonth: 730,
  // True once the user edits the hours field — then it overrides any per-row hours from
  // the data source. Off by default so the data source's own hours are used.
  hoursOverride: false,
  bomName: "",
  ociDiscount: 0,
  oicMessagePacks: 1,
  // Services the user added from the "Add OCI services" panel. Each: {id, catalogId, name,
  // group, sku, unit, basis, values, monthly}. Included in totals and both BOM exports.
  extraServices: [],
  // Diagram & DR options (region names + availability-domain split for the architecture diagram).
  diagramOptions: {
    primaryRegion: "", drRegion: "", splitADs: false, primaryAds: 1,
    enableDr: false, drReplicate: { vms: true, dbs: true, object: true },
  },
  catalog: { groups: [], results: [], group: "", query: "", groupsOpen: {} },
  autoTier: "best",
  shapeOverrides: {},
  costOverrides: {},
  approvedFlags: {},
  flagMenuRow: null,
  hiddenSources: {},
  selectedRows: {},
  crossCloudTopTier: false,
  columnPrefs: {},
  existingInfraCost: 0,
  showMissingOnly: false,
  openaiApiEnabled: false,
  openaiApiConfigured: false,
  openaiApiConnected: false,
  openaiModel: "",
  resultSort: {
    key: "document",
    direction: "asc",
  },
  ramp: {
    months: 12,
    ceiling: 0,
    nextPointId: 1,
    selectedPointId: null,
    points: [],
  },
};

// Restore per-session column visibility choices.
try {
  const savedPrefs = sessionStorage.getItem("ociColumnPrefs");
  if (savedPrefs) state.columnPrefs = JSON.parse(savedPrefs) || {};
} catch (err) {
  state.columnPrefs = {};
}

// Columns that auto-hide when the input has no data for them.
const AUTO_HIDE_COLUMNS = { region: "region", environment: "environment", hours: "hours" };

function autoHiddenColumnSet() {
  const flags = state.pricing?.dataFlags || {};
  const set = new Set();
  for (const [colKey, flagKey] of Object.entries(AUTO_HIDE_COLUMNS)) {
    if (!flags[flagKey]) set.add(colKey);
  }
  return set;
}

function isColumnHidden(key) {
  const pref = state.columnPrefs?.[key];
  if (pref === "show") return false;
  if (pref === "hide") return true;
  return autoHiddenColumnSet().has(key);
}

function saveColumnPrefs() {
  try {
    sessionStorage.setItem("ociColumnPrefs", JSON.stringify(state.columnPrefs || {}));
  } catch (err) {
    /* sessionStorage unavailable */
  }
}

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
  {
    key: "arm",
    label: "Arm (Ampere)",
    description: "Ampere Arm-based A-series flexible shapes.",
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
  hideGpuToggle: document.querySelector("#hideGpuToggle"),
  hideWindowsToggle: document.querySelector("#hideWindowsToggle"),
  rightsizeSwitches: document.querySelectorAll(".rightsize-switch"),
  cpuUnitSwitches: document.querySelectorAll(".cpuunit-switch"),
  cpuUnitDetected: document.getElementById("cpuUnitDetected"),
  cpuUnitRow: document.getElementById("cpuUnitRow"),
  hoursPerMonth: document.querySelector("#hoursPerMonth"),
  exportExcel: document.querySelector("#exportExcel"),
  exportFullBom: document.querySelector("#exportFullBom"),
  downloadDiagram: document.querySelector("#downloadDiagram"),
  exportJson: document.querySelector("#exportJson"),
  loadWorkflow: document.querySelector("#loadWorkflow"),
  loadWorkflowFile: document.querySelector("#loadWorkflowFile"),
  loadPrevBom: document.querySelector("#loadPrevBom"),
  loadWorkflowStatus: document.querySelector("#loadWorkflowStatus"),
  convertBomBtn: document.querySelector("#convertBomBtn"),
  convertBomFile: document.querySelector("#convertBomFile"),
  convertBomStatus: document.querySelector("#convertBomStatus"),
  bomName: document.querySelector("#bomName"),
  ociDiscount: document.querySelector("#ociDiscount"),
  oicMessagePacks: document.querySelector("#oicMessagePacks"),
  oicMessagePacksControl: document.querySelector("#oicMessagePacksControl"),
  crossCloudTile: document.querySelector("#crossCloudTile"),
  addServicesToggle: document.querySelector("#addServicesToggle"),
  addServicesBody: document.querySelector("#addServicesBody"),
  serviceSearch: document.querySelector("#serviceSearch"),
  serviceChips: document.querySelector("#serviceChips"),
  serviceResults: document.querySelector("#serviceResults"),
  serviceCartList: document.querySelector("#serviceCartList"),
  serviceCartCount: document.querySelector("#serviceCartCount"),
  serviceCartTotal: document.querySelector("#serviceCartTotal"),
  crossCloudResults: document.querySelector("#crossCloudResults"),
  selectedDocTile: document.querySelector("#selectedDocTile"),
  selectedDocName: document.querySelector("#selectedDocName"),
  selectedDocSub: document.querySelector("#selectedDocSub"),
  selectedDocClear: document.querySelector("#selectedDocClear"),
  inventoryNotice: document.querySelector("#inventoryNotice"),
  switchToOnPrem: document.querySelector("#switchToOnPrem"),
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
  rampYearFourTotal: document.querySelector("#rampYearFourTotal"),
  rampYearFiveTotal: document.querySelector("#rampYearFiveTotal"),
  rampYearFourBox: document.querySelector("#rampYearFourBox"),
  rampYearFiveBox: document.querySelector("#rampYearFiveBox"),
  rampContractNote: document.querySelector("#rampContractNote"),
  rampHeading: document.querySelector("#rampHeading"),
  costDonut: document.querySelector("#costDonut"),
  costLegend: document.querySelector("#costLegend"),
  topListHeading: document.querySelector("#topListHeading"),
  topWorkloads: document.querySelector("#topWorkloads"),
  detailHeading: document.querySelector("#detailHeading"),
  resultRowCount: document.querySelector("#resultRowCount"),
  resultsTable: document.querySelector("#resultsTable"),
  priceSpinner: document.querySelector("#priceSpinner"),
  sourceFilterPanel: document.querySelector("#sourceFilterPanel"),
  sourceFilterList: document.querySelector("#sourceFilterList"),
  sourceFilterAll: document.querySelector("#sourceFilterAll"),
  sourceFilterNone: document.querySelector("#sourceFilterNone"),
  bulkActionBar: document.querySelector("#bulkActionBar"),
  bulkSelCount: document.querySelector("#bulkSelCount"),
  bulkCostAction: document.querySelector("#bulkCostAction"),
  bulkApply: document.querySelector("#bulkApply"),
  bulkClear: document.querySelector("#bulkClear"),
  steps: document.querySelectorAll(".step"),
};

// "Add OCI services to the BOM" expand/collapse. Delegated on document and re-querying
// the nodes on every click, so it works regardless of load order or any later re-render
// (a stale node reference or an init error further down can't break it).
document.addEventListener("click", (event) => {
  const toggle = event.target.closest("#addServicesToggle, #diagramOptionsToggle");
  if (!toggle) return;
  const bodyId = toggle.id === "diagramOptionsToggle" ? "#diagramOptionsBody" : "#addServicesBody";
  const body = document.querySelector(bodyId);
  if (!body) return;
  const willOpen = body.hasAttribute("hidden");
  body.toggleAttribute("hidden", !willOpen);
  toggle.setAttribute("aria-expanded", willOpen ? "true" : "false");
  toggle.classList.toggle("is-open", willOpen);
  const icon = toggle.querySelector(".add-services-toggle-icon");
  if (icon) icon.textContent = willOpen ? "－" : "＋";  // − when open, ＋ when closed
  if (toggle.id === "addServicesToggle" && willOpen && typeof fetchCatalog === "function"
      && !(state.catalog && state.catalog.groups && state.catalog.groups.length)) {
    fetchCatalog();
  }
});

// Diagram & DR options: region picks + AD split. The primary region's AD count enables
// the "split across ADs" toggle; a 1-AD region can't split.
const state_diagramOptions_default = {
  primaryRegion: "", drRegion: "", splitADs: false, primaryAds: 1,
  enableDr: false, drReplicate: { vms: true, dbs: true, object: true },
};
function _syncAdSplitControl() {
  const sel = document.querySelector("#primaryRegion");
  const chk = document.querySelector("#splitAcrossADs");
  const hint = document.querySelector("#adSplitHint");
  if (!sel || !chk) return;
  const ads = Number(sel.selectedOptions[0]?.dataset.ads || 1);
  state.diagramOptions.primaryRegion = sel.value;
  state.diagramOptions.primaryAds = ads;
  chk.disabled = ads < 2;
  if (ads < 2) { chk.checked = false; state.diagramOptions.splitADs = false; }
  if (hint) hint.textContent = ads >= 2 ? `${ads} availability domains available` : "Pick a multi-AD region to enable";
}
document.querySelector("#primaryRegion")?.addEventListener("change", _syncAdSplitControl);
document.querySelector("#splitAcrossADs")?.addEventListener("change", (e) => {
  state.diagramOptions.splitADs = !!e.target.checked;
});
document.querySelector("#drRegion")?.addEventListener("change", (e) => {
  state.diagramOptions.drRegion = e.target.value;
});
// Enable-DR toggle reveals the DR sub-options (region + which resources to replicate).
document.querySelector("#enableDr")?.addEventListener("change", (e) => {
  const on = !!e.target.checked;
  state.diagramOptions.enableDr = on;
  const sub = document.querySelector("#drSubOptions");
  if (sub) sub.hidden = !on;
});
function _syncDrReplicate() {
  state.diagramOptions.drReplicate = {
    vms: !!document.querySelector("#drRepVms")?.checked,
    dbs: !!document.querySelector("#drRepDbs")?.checked,
    object: !!document.querySelector("#drRepObj")?.checked,
  };
}
["#drRepVms", "#drRepDbs", "#drRepObj"].forEach((sel) =>
  document.querySelector(sel)?.addEventListener("change", _syncDrReplicate));

function rowSourceName(row) {
  return row.fullServiceMapping?.sourceService || row.sourceService || fallbackEntityName(row, "Source line");
}

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

// OCPU / RAM only count as "missing" for compute rows. In cloud-bill mode a storage,
// network, or other non-compute line legitimately has no OCPU/RAM, so leave it blank.
function cellIsMissing(row, fieldKey, valueOverride) {
  const value = valueOverride !== undefined ? valueOverride : row[fieldKey];
  if (hasCellContent(value)) return false;
  if (state.intakeMode === "cloud_bill" && (fieldKey === "resource_ocpus" || fieldKey === "resource_memory_gb")) {
    const prod = String(row.oci_product || "").toLowerCase();
    const isCompute = prod.includes("virtual machine") || prod.includes("compute") || prod.includes("container instance");
    return isCompute; // blank OCPU/RAM is only "missing" when the row is compute
  }
  return true;
}

function fieldHasContent(field) {
  if (!field?.key) return false;
  return state.rows.some((row) => hasCellContent(row[field.key]));
}

function shouldShowField(field) {
  return isManualField(field) || fieldHasContent(field);
}

function rowHasMissingData(row, fields = previewFields()) {
  return fields.some((field) => cellIsMissing(row, field.key));
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
  if (vendor.includes("arm") || vendor.includes("ampere")) return "arm";
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

function processorLogo(key) {
  if (key === "amd") return `<span class="processor-logo amd-logo"><span>AMD</span><i aria-hidden="true"></i></span>`;
  if (key === "intel") return `<span class="processor-logo intel-logo"><span>intel</span></span>`;
  if (key === "arm") return `<span class="processor-logo arm-logo"><span>Ampere</span></span>`;
  return `<span class="processor-logo match-logo"><span>Best&nbsp;Match</span></span>`;
}

function renderProcessorPicker() {
  if (!els.processorPicker) return;
  const vendorTiles = PROCESSOR_VENDORS.map((vendor) => {
    const shapeCount = shapesForVendor(vendor.key).length;
    const countLabel = `${formatNumber(shapeCount)} ${shapeCount === 1 ? "shape" : "shapes"}`;
    const isSelected = !state.auto && vendor.key === state.selectedVendor;
    return `
      <button
        class="processor-button ${isSelected ? "is-selected" : ""}"
        type="button"
        data-processor-vendor="${escapeHtml(vendor.key)}"
        aria-expanded="${isSelected ? "true" : "false"}"
        aria-controls="shapeDropdown"
      >
        ${processorLogo(vendor.key)}
        <em>${escapeHtml(countLabel)}</em>
      </button>
    `;
  }).join("");

  const matchTile = `
    <button
      class="processor-button processor-match ${state.auto ? "is-selected" : ""}"
      type="button"
      data-processor-match="1"
      title="Map each workload to the best OCI shape for its own CPU vendor and generation."
    >
      ${processorLogo("match")}
      <em>auto per workload</em>
    </button>
  `;

  const tierToggle = state.auto
    ? `<div class="match-tier-toggle">
         <span class="match-tier-label">Best Match maps to</span>
         <div class="mode-switch match-tier-switch" role="group" aria-label="Best Match shape generation">
           <button type="button" class="mode-opt ${state.autoTier === "top" ? "" : "is-active"}" data-auto-tier="best" title="Map each workload to the OCI shape of the equivalent processor generation to its source.">Equivalent generation</button>
           <button type="button" class="mode-opt ${state.autoTier === "top" ? "is-active" : ""}" data-auto-tier="top" title="Map every workload to OCI's newest shape (E6 Ax / X12 Ax / A4 Ax).">Top of the line</button>
         </div>
       </div>`
    : "";

  els.processorPicker.innerHTML = vendorTiles + matchTile + tierToggle;

  els.processorPicker.querySelectorAll("[data-auto-tier]").forEach((button) => {
    button.addEventListener("click", () => {
      state.autoTier = button.dataset.autoTier === "top" ? "top" : "best";
      renderProcessorPicker();
    });
  });

  els.processorPicker.querySelectorAll("[data-processor-vendor]").forEach((button) => {
    button.addEventListener("click", () => {
      state.auto = false;
      setProcessorVendor(button.dataset.processorVendor);
      applyAutoUI();
      renderProcessorPicker();
    });
  });
  els.processorPicker.querySelector("[data-processor-match]")?.addEventListener("click", () => {
    state.auto = true;
    applyAutoUI();
    renderProcessorPicker();
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
  // OIC message packs only apply in cloud-bill mode (SQS/SNS/Transfer Family mapping).
  els.oicMessagePacksControl?.classList.toggle("is-hidden", !cloudBill);
  if (els.providerHint) {
    els.providerHint.value = state.providerHint;
  }
  // Cloud bill accepts several formats; Chrome can grey out CSV/TSV even when listed,
  // so don't filter at all here — the backend validates the file type on upload.
  els.fileInput.accept = cloudBill ? "" : ".xlsx,.xls";
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
  if (els.shapeFamily) els.shapeFamily.textContent = shape.family || "OCI flex shape";
  if (els.shapeDetailTitle) els.shapeDetailTitle.textContent = shape.label || "Selected shape";
  if (els.shapeDetailSummary) els.shapeDetailSummary.textContent = shape.summary || "Selected shape rates will be applied to approved rows.";
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
  // Enable/disable Rightsize based on whether the selected shape supports it.
  if (typeof syncRightsizeAvailability === "function") syncRightsizeAvailability();
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

// CPU-unit interpretation. The parser stores the CPU column already halved
// (raw vCPU / 2 = OCPU under the default vCPU assumption). "Already OCPUs" means the
// source count is the OCPU count, so the review/pricing value is doubled back to the
// raw count. "Auto" detects vCPU vs OCPU from the original header, defaulting to vCPU.
function resolvedCpuUnit() {
  if (state.cpuUnit === "vcpu" || state.cpuUnit === "ocpu") return state.cpuUnit;
  const f = (state.fields || []).find((x) => x && x.cpuSourceLabel);
  const src = String(f?.cpuSourceLabel || "").toLowerCase();
  if (src.includes("ocpu")) return "ocpu";
  if (src.includes("vcpu") || src.includes("virtual cpu")) return "vcpu";
  return "vcpu";
}
function cpuDisplayMult() {
  return resolvedCpuUnit() === "ocpu" ? 2 : 1;
}
function isCpuField(field) {
  return !!(field && field.cpuSourceLabel);
}
function formatCpuDisplay(n) {
  const r = Math.round(n * 1000) / 1000;
  return Number.isInteger(r) ? String(r) : String(r);
}
function updateCpuUnitHint() {
  if (!els.cpuUnitDetected) return;
  if (state.cpuUnit === "auto" && (state.fields || []).some((f) => f && f.cpuSourceLabel)) {
    const r = resolvedCpuUnit();
    els.cpuUnitDetected.textContent =
      "Auto-detected: " + (r === "ocpu" ? "already OCPUs" : "vCPUs (halved for OCI)");
    els.cpuUnitDetected.hidden = false;
  } else {
    els.cpuUnitDetected.hidden = true;
  }
}

// Pre-flight data check. Runs on every upload: says exactly which inputs the file carries
// and, for the ones it doesn't, what the app will therefore leave blank. Nothing downstream
// (BOM sheets, architecture diagram, topology) is allowed to invent what isn't here.
const DATA_CHECK_CONSEQUENCE = {
  cpu: "no compute can be priced",
  memory: "no compute can be priced",
  storage: "block storage is left out of the BOM",
  os: "no OS split and no Windows licensing line",
  server: "Compute sheet rows will be unnamed",
  environment: "the Environment column stays blank",
  tier: "the Tier column stays blank; spokes can't be split by tier",
  application: "the Applications sheet and Master Application column stay empty",
  site: "no site-to-region topology diagram is drawn",
};

function renderDataCheck(check) {
  const panel = document.getElementById("dataCheck");
  const list = document.getElementById("dataCheckList");
  const note = document.getElementById("dataCheckNote");
  if (!panel || !list) return;
  if (!check || !Array.isArray(check.signals) || !check.signals.length) {
    panel.hidden = true;
    return;
  }
  list.innerHTML = "";
  check.signals.forEach((s) => {
    const li = document.createElement("li");
    li.className = s.present ? "dc-ok" : "dc-missing";
    const detail = s.present
      ? `${s.column} — ${formatNumber(s.populated)} of ${formatNumber(s.total)} rows`
      : `not in this file — ${DATA_CHECK_CONSEQUENCE[s.key] || "left blank"}`;
    li.innerHTML =
      `<span class="dc-mark" aria-hidden="true">${s.present ? "✓" : "—"}</span>` +
      `<span class="dc-label">${escapeHtml(s.label)}</span>` +
      `<span class="dc-detail">${escapeHtml(detail)}</span>`;
    list.appendChild(li);
  });
  const missing = check.signals.filter((s) => !s.present).map((s) => s.label);
  const caps = check.capabilities || {};
  const bits = [];
  if (!caps.priceCompute) bits.push("Compute can't be priced without both a CPU and a memory column.");
  if (caps.segmentBy) {
    const by = { tier: "Tier", environment: "Environment", os: "OS family", application: "Application" }[caps.segmentBy];
    bits.push(`Architecture spokes will be split by ${by}.`);
  }
  if (missing.length) bits.push(`Missing: ${missing.join(", ")}. Those stay blank.`);
  note.textContent = bits.join(" ");
  note.hidden = !bits.length;
  panel.hidden = false;
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
      td.classList.toggle("is-missing-data", cellIsMissing(row, field.key));
      const cellEditor = document.createElement("div");
      cellEditor.className = "cell-editor";
      const input = document.createElement("input");
      input.type = "text";
      // The OCPUs column reflects the CPU-unit toggle: stored value is the parsed
      // (halved) OCPU; display it x2 when the source column is "Already OCPUs".
      const cpuField = isCpuField(field);
      const cpuMult = cpuField ? cpuDisplayMult() : 1;
      const storedVal = row[field.key];
      if (cpuField && storedVal !== "" && storedVal != null && !isNaN(Number(storedVal))) {
        input.value = formatCpuDisplay(Number(storedVal) * cpuMult);
      } else {
        input.value = storedVal ?? "";
      }
      input.placeholder = cellIsMissing(row, field.key) ? "Missing data" : "";
      input.dataset.rowIndex = String(rowIndex);
      input.dataset.fieldKey = field.key;
      input.setAttribute("aria-label", `${field.label}, row ${rowIndex + 1}`);
      input.addEventListener("input", () => {
        if (cpuField && input.value !== "" && !isNaN(Number(input.value))) {
          // Store back in the parsed (halved) OCPU space so pricing stays consistent.
          row[field.key] = Number(input.value) / cpuMult;
        } else {
          row[field.key] = input.value;
        }
        const isMissing = cellIsMissing(row, field.key, input.value);
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
  // CPU-unit override only applies to on-prem inventory (cloud bills carry OCPU/vCPU
  // in the usage rows), so hide the control in cloud-bill mode.
  if (els.cpuUnitRow) els.cpuUnitRow.hidden = isCloudBillMode();
  updateCpuUnitHint();
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

const PROVIDER_NAME_TO_VALUE = { aws: "aws", azure: "azure", gcp: "gcp" };

function showSelectedDoc(name, sub) {
  if (!els.selectedDocTile) return;
  if (!name) {
    els.selectedDocTile.hidden = true;
    return;
  }
  els.selectedDocTile.hidden = false;
  if (els.selectedDocName) els.selectedDocName.textContent = name;
  if (els.selectedDocSub) els.selectedDocSub.textContent = sub || "";
}

async function uploadFile(file) {
  if (!file) return;
  state.lastUploadFile = file;
  showSelectedDoc(file.name, "Reading file…");
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
    const docModeLabel = state.intakeMode === "cloud_bill"
      ? `${payload.metadata?.detectedProvider || "Cloud"} bill`
      : "On-prem inventory";
    showSelectedDoc(payload.fileName, `${formatNumber(payload.rows.length)} rows · ${docModeLabel}`);
    if (els.inventoryNotice) els.inventoryNotice.hidden = !payload.metadata?.inventorySuspected;
    // Warn if a finished comparison/BOM workbook was dropped into cloud-bill mode.
    const cmpNotice = document.getElementById("comparisonBomNotice");
    if (cmpNotice) {
      const msg = payload.comparisonBomWarning;
      const txt = document.getElementById("comparisonBomNoticeText");
      if (msg && txt) txt.textContent = msg;
      cmpNotice.hidden = !msg;
    }
    // Reflect the detected/guessed provider in the toggle so the user sees the guess
    // and can override it. (Only when they hadn't already forced a provider.)
    if (state.intakeMode === "cloud_bill" && state.providerHint === "auto") {
      const guessed = PROVIDER_NAME_TO_VALUE[(payload.metadata?.detectedProvider || "").toLowerCase()];
      if (guessed) {
        state.providerHint = guessed;
        if (els.providerHint) els.providerHint.value = guessed;
      }
    }
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
    renderDataCheck(payload.dataCheck);
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
  renderDataCheck(null);
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

async function priceRows({ keepView = false } = {}) {
  // Non-fading floating spinner so in-place edits (e.g. removing a large
  // selection from the BOM) show progress without blanking the screen.
  if (els.priceSpinner) els.priceSpinner.hidden = false;
  // Let the spinner paint before any heavy synchronous render that follows.
  await new Promise((r) => requestAnimationFrame(() => r()));
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
          hideGpuPricing: state.hideGpuPricing,
          hideWindowsPricing: state.hideWindowsPricing,
          rightsize: state.rightsize,
          cpuUnit: state.cpuUnit,
          auto: state.auto,
          autoTier: state.autoTier,
          shapeOverrides: state.shapeOverrides,
          costOverrides: state.costOverrides,
          hoursPerMonth: state.hoursPerMonth,
          hoursOverride: state.hoursOverride,
          oicMessagePacks: state.oicMessagePacks,
        }),
      },
      70000,
    );
    if (!response.ok) {
      throw new Error(payload.error || "Pricing failed.");
    }
    state.pricing = payload;
    updateCpuUnitHint();
    renderPricing(payload);
    renderResults(payload);
    // When re-pricing in place (e.g. editing a shape dropdown), don't jump the page.
    if (keepView) {
      const y = window.scrollY;
      requestAnimationFrame(() => window.scrollTo({ top: y }));
    } else {
      showResultsPage();
      setStep("price");
    }
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
    if (els.priceSpinner) els.priceSpinner.hidden = true;
  }
}

// The Full BOM takes a few seconds (12 sheets + the architecture diagram), so the overlay
// walks through what it's doing rather than sitting on one frozen line — otherwise a slow
// build is indistinguishable from a dead button.
const FULL_BOM_STAGES = [
  "Pricing every server against the OCI rate card…",
  "Building Compute, Storage and Applications sheets…",
  "Rendering the OCI architecture diagram…",
  "Laying out the Pricing Overview and Consumption Ramp…",
  "Finishing the workbook — almost there…",
];

async function exportToExcel(template = "quick") {
  const isFull = template === "full";
  const button = isFull ? els.exportFullBom : els.exportExcel;
  const original = button ? button.textContent : "";
  const overlay = document.querySelector("#exportOverlay");
  const overlayText = overlay ? overlay.querySelector(".export-overlay-text") : null;

  // Don't fail silently. Without pricing there is nothing to export, and a dead-looking
  // button is worse than a message saying why.
  if (!state.pricing) {
    els.engineStatus.textContent =
      "Nothing to export yet — run \"Reprice estimate\" first, then try the BOM again.";
    return;
  }

  let stageTimer = null;
  let failed = false;
  if (button) {
    button.disabled = true;
    button.textContent = isFull ? "Building Full BOM..." : "Exporting...";
  }
  if (overlayText) {
    const stages = FULL_BOM_STAGES;
    overlayText.textContent = isFull ? stages[0] : "Generating your Excel workbook…";
    if (isFull) {
      let i = 0;
      stageTimer = setInterval(() => {
        i = Math.min(i + 1, stages.length - 1);
        overlayText.textContent = stages[i];
      }, 1200);
    }
  }
  if (overlay) overlay.hidden = false;
  try {
    const rampVals = (typeof rampMonthlyValues === "function" && state.ramp.points.length)
      ? rampMonthlyValues()
      : [];
    // Short ramps (12/24 mo) still print a full 3-year contract: months past the ramp
    // run at the full BOM maximum. Longer ramps (36/60) already fill the contract.
    const monthly = rampVals.slice();
    if (rampVals.length) {
      const rampYears = Math.max(1, Math.round((state.ramp.months || 12) / 12));
      const contractMonths = Math.max(rampYears, 3) * 12;
      for (let m = monthly.length; m < contractMonths; m += 1) monthly.push(state.ramp.ceiling);
    }
    const ramp = { ceiling: state.ramp.ceiling, monthly };
    const response = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        fields: state.fields,
        rows: state.rows,
        shape: state.selectedShape,
        intakeMode: state.intakeMode,
        providerHint: state.providerHint,
        fullServiceBeta: state.fullServiceBeta,
        hideGpuPricing: state.hideGpuPricing,
        hideWindowsPricing: state.hideWindowsPricing,
        rightsize: state.rightsize,
        cpuUnit: state.cpuUnit,
        auto: state.auto,
        autoTier: state.autoTier,
        shapeOverrides: state.shapeOverrides,
        costOverrides: state.costOverrides,
        hoursPerMonth: state.hoursPerMonth,
        hoursOverride: state.hoursOverride,
        bomName: state.bomName || "",
        ociDiscount: (state.ociDiscount || 0) / 100,
        oicMessagePacks: state.oicMessagePacks,
        ramp,
        existingInfraCost: state.existingInfraCost || 0,
        workflowState: collectWorkflowState(),
        // A converted OCI BOM is already priced; export it in the AWS cloud-compare
        // workbook format straight from the converted pricing (no re-pricing).
        converted: !!(state.pricing && state.pricing.converted),
        convertedPricing: (state.pricing && state.pricing.converted)
          ? { rows: state.pricing.rows, totals: state.pricing.totals }
          : null,
        // Services added from the "Add OCI services" panel — priced server-side and folded
        // into the export totals and the matching Pricing Overview lines.
        extraServices: state.extraServices || [],
        // Region / AD-split / DR-region choices for the architecture diagram.
        diagramOptions: state.diagramOptions || {},
        template, // "quick" = compact BOM+Overview, "full" = 12-sheet deliverable
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
    // Filename = the BOM name the user typed at the top + today's date, so repeat exports
    // never silently overwrite each other in Downloads.
    const safeName = (state.bomName || "").trim().replace(/[\\/:*?"<>|]+/g, "_").replace(/\s+/g, "_");
    const suffix = isFull ? "_Full_BOM" : "_BOM";
    const today = new Date();
    const stamp = [
      today.getFullYear(),
      String(today.getMonth() + 1).padStart(2, "0"),
      String(today.getDate()).padStart(2, "0"),
    ].join("-");
    link.download = `${safeName || "OCI"}${suffix}_${stamp}.xlsx`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    // Confirm it landed — the browser saves silently, which reads as "nothing happened".
    els.engineStatus.textContent = `${isFull ? "Full BOM" : "Quick BOM"} downloaded: ${link.download}`;
  } catch (error) {
    // A failed export used to just blink the overlay and write to a status line nobody
    // was looking at, so it read as "nothing happened". Say it out loud, and don't
    // dismiss until the user acknowledges it.
    failed = true;
    const msg = `${isFull ? "Full BOM" : "Quick BOM"} export failed — ${error.message}`;
    els.engineStatus.textContent = msg;
    console.error("BOM export failed", error);
    if (stageTimer) clearInterval(stageTimer);
    stageTimer = null;
    if (overlayText) {
      overlayText.innerHTML = "";
      const p = document.createElement("p");
      p.className = "export-error-msg";
      p.textContent = msg;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "ghost-button";
      btn.textContent = "Dismiss";
      btn.addEventListener("click", () => {
        if (overlay) overlay.hidden = true;
        overlayText.textContent = "";
      });
      overlayText.append(p, btn);
    }
    const spinner = overlay ? overlay.querySelector(".export-spinner") : null;
    if (spinner) spinner.hidden = true;
  } finally {
    if (stageTimer) clearInterval(stageTimer);
    if (button) {
      button.disabled = false;
      button.textContent = original;
    }
    const spinner = overlay ? overlay.querySelector(".export-spinner") : null;
    if (!failed) {
      if (spinner) spinner.hidden = false;
      if (overlay) overlay.hidden = true;
    }
  }
}

// Capture the COMPLETE app state so a saved workflow restores the window exactly:
// the table data plus every user modification (shape/cost overrides, approvals,
// filters, selections, discount, ramp, column choices, mode, etc.).
function collectWorkflowState() {
  return {
    __workflow: "oci-bom-app",
    version: 1,
    savedAt: new Date().toISOString(),
    intakeMode: state.intakeMode,
    providerHint: state.providerHint,
    fullServiceBeta: state.fullServiceBeta,
    hideGpuPricing: state.hideGpuPricing,
    hideWindowsPricing: state.hideWindowsPricing,
    rightsize: state.rightsize,
    cpuUnit: state.cpuUnit,
    auto: state.auto,
    autoTier: state.autoTier,
    hoursPerMonth: state.hoursPerMonth,
    bomName: state.bomName,
    ociDiscount: state.ociDiscount,
    oicMessagePacks: state.oicMessagePacks,
    selectedShape: state.selectedShape,
    existingInfraCost: state.existingInfraCost,
    crossCloudTopTier: state.crossCloudTopTier,
    fields: state.fields,
    rows: state.rows,
    shapeOverrides: state.shapeOverrides,
    costOverrides: state.costOverrides,
    approvedFlags: state.approvedFlags,
    hiddenSources: state.hiddenSources,
    selectedRows: state.selectedRows,
    columnPrefs: state.columnPrefs,
    resultSort: state.resultSort,
    ramp: {
      months: state.ramp.months,
      ceiling: state.ramp.ceiling,
      points: state.ramp.points,
    },
  };
}

async function exportWorkflowJson() {
  if (!state.rows || !state.rows.length) return;
  const btn = els.exportJson;
  const original = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "Saving…"; }
  if (els.priceSpinner) {
    els.priceSpinner.querySelector(".price-spinner-text").textContent = "Saving workflow…";
    els.priceSpinner.hidden = false;
  }
  // Let the spinner paint before the (potentially large) serialize/stringify.
  await new Promise((r) => requestAnimationFrame(() => r()));
  try {
    const blob = new Blob([JSON.stringify(collectWorkflowState(), null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    const safe = (state.bomName || "workflow").trim().replace(/[\\/:*?"<>|]+/g, "_").replace(/\s+/g, "_") || "workflow";
    link.download = `${safe}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = original; }
    if (els.priceSpinner) {
      els.priceSpinner.hidden = true;
      els.priceSpinner.querySelector(".price-spinner-text").textContent = "Updating…";
    }
  }
}

// Restore a saved workflow object into state, then re-price to rebuild the window.
async function applyWorkflowState(wf) {
  if (!wf || !wf.rows) throw new Error("That file has no saved workflow data.");
  const assign = [
    "intakeMode", "providerHint", "fullServiceBeta", "hideGpuPricing",
    "hideWindowsPricing", "rightsize", "auto", "autoTier", "hoursPerMonth", "hoursOverride",
    "bomName", "ociDiscount", "oicMessagePacks", "selectedShape", "existingInfraCost",
    "crossCloudTopTier", "fields", "rows", "shapeOverrides", "costOverrides",
    "approvedFlags", "hiddenSources", "selectedRows", "columnPrefs", "resultSort",
  ];
  assign.forEach((k) => { if (wf[k] !== undefined) state[k] = wf[k]; });
  if (wf.ramp) {
    state.ramp.months = wf.ramp.months || state.ramp.months;
    state.ramp.ceiling = wf.ramp.ceiling || 0;
    state.ramp.points = Array.isArray(wf.ramp.points) ? wf.ramp.points : [];
    state.ramp.signature = null; // force the ramp to honor the restored points
  }
  // Reflect restored simple inputs back into their controls if present.
  if (els.bomName) els.bomName.value = state.bomName || "";
  if (els.ociDiscount) els.ociDiscount.value = state.ociDiscount || 0;
  if (els.oicMessagePacks) els.oicMessagePacks.value = state.oicMessagePacks || 1;
  if (typeof renderTable === "function") renderTable();
  await priceRows();
  // Opening a previous BOM jumps straight to the results page (page 4).
  if (state.pricing) showResultsPage();
}

// Show the dropped/selected workflow file name + whether it was accepted.
function setWorkflowStatus(name, message, state) {
  const el = els.loadWorkflowStatus;
  if (!el) return;
  el.hidden = false;
  el.className = `load-workflow-status lws-${state}`;
  const icon = state === "ok" ? "✓" : state === "error" ? "✕" : "⏳";
  el.querySelector(".lws-icon").textContent = icon;
  el.querySelector(".lws-name").textContent = name || "";
  el.querySelector(".lws-state").textContent = message || "";
}

async function loadWorkflowFromFile(file) {
  if (!file) return;
  const nm = file.name || "file";
  const okExt = /\.(json|xlsx)$/i.test(nm);
  setWorkflowStatus(nm, okExt ? "loaded — checking…" : "not a .json or .xlsx file", okExt ? "loading" : "error");
  if (!okExt) return;
  if (els.priceSpinner) {
    els.priceSpinner.querySelector(".price-spinner-text").textContent = "Loading workflow…";
    els.priceSpinner.hidden = false;
  }
  try {
    let wf;
    if (nm.toLowerCase().endsWith(".json")) {
      wf = JSON.parse(await file.text());
    } else {
      const fd = new FormData();
      fd.append("file", file);
      const resp = await fetch("/api/load-workflow", { method: "POST", body: fd });
      const payload = await resp.json();
      if (!resp.ok) throw new Error(payload.error || "Could not read workflow.");
      wf = payload.workflow;
    }
    await applyWorkflowState(wf);
    setWorkflowStatus(nm, "✓ Accepted — BOM restored", "ok");
  } catch (error) {
    els.engineStatus.textContent = `Workflow load failed: ${error.message}`;
    if (els.priceSpinner) els.priceSpinner.hidden = true;
    setWorkflowStatus(nm, `✕ Not accepted — ${error.message}`, "error");
  } finally {
    if (els.priceSpinner) els.priceSpinner.querySelector(".price-spinner-text").textContent = "Updating…";
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
             <div class="kpi"><span>Shape</span><strong>${pricing.auto ? "Best Match" : escapeHtml(shape.shortLabel || shape.label)}</strong></div>`
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
  if (state.ramp.points.length >= 12) return selectedRampPoint();
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

// OCI monthly total after the user's OCI discount (set near the ramp graph),
// using the same per-row rule as the export: carried/free lines stay at cost,
// everything else is reduced by the discount. At 0% this equals totals.monthly.
function ociEffectiveMonthly(pricing) {
  if (!pricing || !pricing.totals) return 0;
  const d = (state.ociDiscount || 0) / 100;
  if (!d) return Number(pricing.totals.monthly || 0);
  const rows = pricing.rows || [];
  let t = 0;
  for (const r of rows) {
    const m = Number(r.monthly || 0);
    if ((r.costAction || "") === "carry" || !m) t += m;
    else t += m * (1 - d);
  }
  return t;
}

function ociMonthlyWithWindows(pricing) {
  // OCI services monthly + Windows 3rd-party licensing (0 when Hide Windows is on), so the
  // ramp ceiling matches the BOM's Total Monthly Cost and both ramps carry Windows.
  const services = Number(pricing?.totals?.monthly || 0);
  const windows = (pricing?.rows || []).reduce(
    (t, r) => t + Number(r.windowsLicenseMonthly || 0), 0);
  return Math.max(0, services + windows);
}

function initializeConsumptionRamp(pricing) {
  const ceiling = ociMonthlyWithWindows(pricing);
  const shapeKey = pricing.selectedShape?.key || state.selectedShape;
  const signature = `${shapeKey}:${ceiling}:${pricing.rows.length}`;
  if (state.ramp.signature !== signature) {
    state.ramp.signature = signature;
    state.ramp.ceiling = ceiling;
    state.ramp.nextPointId = 1;
    // Seed 4 evenly-spaced ramp dots regardless of ramp length (e.g. 12-month
    // ramp -> dots at months 3, 6, 9, 12 climbing to the BOM maximum).
    const seedDots = 4;
    const seedMonths = state.ramp.months || 12;
    state.ramp.points = Array.from({ length: seedDots }, (_, i) =>
      newRampPoint(
        Math.max(1, Math.round((seedMonths * (i + 1)) / seedDots)),
        ceiling * ((i + 1) / seedDots),
      ),
    );
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
  const xTicks = [];
  // Short ramps (<=12 mo) label every month 1..N; longer ramps label every 12.
  if (months <= 12) {
    for (let m = 1; m <= months; m += 1) xTicks.push(m);
  } else {
    for (let m = 0; m <= months; m += 12) xTicks.push(m);
  }

  els.rampChart.setAttribute("viewBox", `0 0 ${width} ${height}`);
  els.rampCeilingLabel.textContent = `BOM maximum ${formatCurrency(ceiling)}/mo`;
  els.rampPeakMonth.value = selected ? selected.month : "";
  els.rampPeakMonthly.max = ceiling.toFixed(2);
  els.rampPeakMonthly.value = selected ? selected.monthly.toFixed(2) : "";
  els.removeRampPoint.disabled = state.ramp.points.length <= 1;
  els.addRampPoint.disabled = state.ramp.points.length >= 12;

  const values = rampMonthlyValues();
  const rampYears = Math.max(1, Math.round(months / 12));
  // Short ramps (12/24 mo) still model a full 3-year contract: the ramp covers the
  // early months and every year after the ramp runs at the full BOM maximum.
  const contractYears = Math.max(rampYears, 3);
  const contractMonths = contractYears * 12;
  const fullYear = ceiling * 12;
  // OCI discount applies to the money tiles (matching the export) but NOT to the ramp
  // dots/graph — the curve stays a list-price consumption shape. Exclude 3rd-party
  // licensing from the discount by deriving the ratio from the priced totals.
  const p = state.pricing;
  let discRatio = 1;
  if (p && p.totals) {
    const listCeil = ociMonthlyWithWindows(p);
    const windows = Math.max(0, listCeil - Number(p.totals.monthly || 0));
    if (listCeil > 0) discRatio = (ociEffectiveMonthly(p) + windows) / listCeil;
  }
  const yearListSpend = (y) =>
    y < rampYears
      ? values.slice(y * 12, (y + 1) * 12).reduce((sum, value) => sum + value, 0)
      : fullYear;
  let contractListTotal = 0;
  for (let y = 0; y < contractYears; y += 1) contractListTotal += yearListSpend(y);

  els.rampThreeYearTotal.textContent = formatCurrency(contractListTotal * discRatio);
  els.rampAvgMonthly.textContent = formatCurrency((contractListTotal * discRatio) / contractMonths);
  [
    [els.rampYearOneTotal, yearListSpend(0)],
    [els.rampYearTwoTotal, yearListSpend(1)],
    [els.rampYearThreeTotal, yearListSpend(2)],
    [els.rampYearFourTotal, yearListSpend(3)],
    [els.rampYearFiveTotal, yearListSpend(4)],
  ].forEach(([element, listValue]) => {
    if (!element) return;
    const value = listValue * discRatio;
    element.textContent = formatCompactCurrency(value);
    element.title = formatCurrency(value);
  });
  // Show/hide years 4-5 for the chosen contract length.
  if (els.rampYearFourBox) els.rampYearFourBox.hidden = contractYears < 4;
  if (els.rampYearFiveBox) els.rampYearFiveBox.hidden = contractYears < 5;
  const years = contractYears;
  if (els.rampHeading) {
    const m = state.ramp.months || 36;
    els.rampHeading.textContent = `Build a ${m}-month ramp`;
    // Keep the "selected dot month" control in step with the chosen ramp length.
    if (els.rampPeakMonth) {
      els.rampPeakMonth.max = String(m);
      const hint = els.rampPeakMonth.parentElement?.querySelector("small");
      if (hint) hint.textContent = `Month 1 to month ${m}`;
    }
  }
  if (els.rampContractNote) {
    els.rampContractNote.textContent = Array.from({ length: years }, (_, i) => `Year ${i + 1}`).join(" + ");
  }

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

  els.resultsShape.textContent = pricing.auto ? "Best Match" : (shape.label || "Selected shape");
  els.resultsSubtitle.textContent = cloudBill
    ? `${pricing.rows.length} source bill lines reviewed; ${serviceRows} mapped to OCI-equivalent products and ${reviewRows} need review before they affect totals.`
    : pricing.fullServiceBeta
    ? `${pricing.rows.length} approved items priced with OCI service mapping; ${serviceRows} service mappings priced and ${reviewRows} items need review.`
    : `${pricing.rows.length} approved workloads priced on ${shape.label} with ${engineLabel} SKU validation.`;
  els.topListHeading.textContent = cloudBill ? "Top source lines" : "Top workloads";
  els.detailHeading.textContent = cloudBill ? "Cloud bill mapping detail" : "Application Cost Details";
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
  const storageGb = Number(pricing.totals.blockStorageGb || 0) + Number(pricing.totals.fileStorageGb || 0)
    + Number(pricing.totals.cloudStorageGb || 0);
  const storageScale = Math.min(100, Math.max(12, Math.log10(Math.max(10, storageGb || 0)) * 20));
  const discPct = state.ociDiscount || 0;
  const extrasList = extraServicesMonthly();          // list price (for the "before discount" figure)
  const extras = extraServicesEffective();            // after OCI discount (excl. 3rd-party licensing)
  // Windows (and other 3rd-party) licensing is a real OCI charge — include it in the
  // headline so it matches the ramp ceiling, the Full BOM, and the actual OCI bill.
  // It's never discounted (3rd-party), so it's added at list on top of discounted services.
  const windowsLicensing = (pricing.rows || []).reduce(
    (t, r) => t + Number(r.windowsLicenseMonthly || 0), 0);
  const ociEff = ociEffectiveMonthly(pricing) + extras + windowsLicensing;
  const ociEffAnnual = ociEff * 12;
  const extrasMeta = (extras ? ` · incl. ${formatCompactCurrency(extras)} added services` : "")
    + (windowsLicensing ? ` · incl. ${formatCompactCurrency(windowsLicensing)} Windows licensing` : "");
  const pricingCards = `
    ${resultKpiCard({
      label: (cloudBill ? "OCI-equivalent monthly" : "Monthly run rate") + (discPct ? ` (after ${discPct}% discount)` : ""),
      value: formatCompactCurrency(ociEff),
      meta: (discPct
        ? `${formatCompactCurrency(ociEffAnnual)} annualized · ${formatCompactCurrency(pricing.totals.monthly + extrasList + windowsLicensing)} list before discount`
        : `${formatCompactCurrency(ociEffAnnual)} annualized`) + extrasMeta,
      accent: "#c74634",
      fill: monthlyScale,
      primary: true,
      title: discPct
        ? `${formatCurrency(ociEff)} monthly after ${discPct}% OCI discount (list ${formatCurrency(pricing.totals.monthly + extrasList + windowsLicensing)}); 3rd-party licensing excluded from discount`
        : `${formatCurrency(ociEff)} monthly; ${formatCurrency(ociEffAnnual)} annualized`,
    })}
    ${resultKpiCard({
      label: "Flex shape",
      value: pricing.auto ? "Best Match" : (shape.shortLabel || shape.label),
      meta: pricing.auto
        ? "Each workload mapped to its best OCI shape"
        : `$${Number(shape.computeRate || 0).toFixed(4)} OCPU/hr and $${Number(shape.memoryRate || 0).toFixed(4)} GB/hr`,
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
  // Detail table defaults to the document's VM order (not cost-sorted).
  renderResultsTable(pricing.rows.slice(), pricing.fullServiceBeta, cloudBill);
  // Refresh the other-cloud tile if it's currently expanded.
  if (els.crossCloudResults && !els.crossCloudResults.hidden) renderCrossCloud();
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
  // "document" (the default) means keep the original upload/order — no column sort.
  if (state.resultSort.key === "document") return { column: null, direction: "asc" };
  const requestedColumn = columns.find((column) => column.key === state.resultSort.key);
  if (!requestedColumn) return { column: null, direction: "asc" };
  return { column: requestedColumn, direction: state.resultSort.direction === "asc" ? "asc" : "desc" };
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
            if (column.selector) {
              return `<th class="select-col"><input type="checkbox" id="selectAllRows" aria-label="Select all rows"/></th>`;
            }
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

function renderColumnPicker(allColumnsRaw) {
  const menu = document.querySelector("#columnPickerMenu");
  if (!menu) return;
  const allColumns = allColumnsRaw.filter((c) => !c.selector);
  const hiddenCount = allColumns.filter((c) => isColumnHidden(c.key)).length;
  const heading = hiddenCount
    ? `<div class="column-picker-head">${hiddenCount} column${hiddenCount === 1 ? "" : "s"} hidden &mdash; check to show</div>`
    : `<div class="column-picker-head">All columns shown</div>`;
  menu.innerHTML =
    heading +
    allColumns
      .map((c) => {
        const checked = isColumnHidden(c.key) ? "" : "checked";
        return `<label class="column-picker-item"><input type="checkbox" data-col-key="${escapeHtml(c.key)}" ${checked}/> <span>${escapeHtml(c.label)}</span></label>`;
      })
      .join("");
  menu.querySelectorAll("input[data-col-key]").forEach((cb) => {
    cb.addEventListener("change", (e) => {
      const key = e.target.dataset.colKey;
      if (!state.columnPrefs) state.columnPrefs = {};
      state.columnPrefs[key] = e.target.checked ? "show" : "hide";
      saveColumnPrefs();
      rerenderResultsTable();
    });
  });
}

function rerenderResultsTable() {
  if (!state.pricing) return;
  renderResultsTable(
    state.pricing.rows || [],
    state.pricing.fullServiceBeta,
    state.pricing.intakeMode === "cloud_bill" || state.pricing.cloudBillMode,
  );
}

// Build the left-hand source-service filter (distinct names + row counts).
function renderSourceFilter(rows) {
  if (!els.sourceFilterPanel || !els.sourceFilterList) return;
  els.sourceFilterPanel.hidden = false;
  const counts = new Map();
  rows.forEach((r) => {
    const name = rowSourceName(r);
    counts.set(name, (counts.get(name) || 0) + 1);
  });
  const names = [...counts.keys()].sort((a, b) => a.localeCompare(b));
  els.sourceFilterList.innerHTML = names
    .map((name) => {
      const checked = state.hiddenSources[name] ? "" : "checked";
      return `<label class="source-filter-item"><input type="checkbox" data-source-name="${escapeHtml(name)}" ${checked}/> <span class="source-filter-name">${escapeHtml(name)}</span> <span class="source-filter-count">${counts.get(name)}</span></label>`;
    })
    .join("");
}

// Show/refresh the bulk-action bar based on current selection.
function syncBulkBar() {
  if (!els.bulkActionBar) return;
  const ids = Object.keys(state.selectedRows).filter((id) => state.selectedRows[id]);
  const n = ids.length;
  els.bulkActionBar.hidden = n === 0;
  if (els.bulkSelCount) els.bulkSelCount.textContent = `${n} selected`;
  const selectAll = document.querySelector("#selectAllRows");
  if (selectAll) {
    const visibleIds = (state.pricing?.rows || [])
      .filter((r) => !state.hiddenSources[rowSourceName(r)])
      .map((r) => String(r.rowId));
    const selectedVisible = visibleIds.filter((id) => state.selectedRows[id]).length;
    selectAll.checked = visibleIds.length > 0 && selectedVisible === visibleIds.length;
    selectAll.indeterminate = selectedVisible > 0 && selectedVisible < visibleIds.length;
  }
}

function applyBulkCostAction(value) {
  const ids = Object.keys(state.selectedRows).filter((id) => state.selectedRows[id]);
  if (!ids.length) return Promise.resolve();
  ids.forEach((id) => {
    if (value === "estimate" || !value) delete state.costOverrides[id];
    else state.costOverrides[id] = value;
  });
  return priceRows({ keepView: true });
}

function renderResultTableFromColumns(rows, columns) {
  renderColumnPicker(columns);
  const visible = columns.filter((c) => !isColumnHidden(c.key));
  const cols = visible.length ? visible : columns;
  const sortedRows = sortResultRows(rows, cols);
  const body = sortedRows
    .map((row) => `
      <tr>
        ${cols.map((column) => `<td>${column.render(row)}</td>`).join("")}
      </tr>
    `)
    .join("");
  els.resultsTable.innerHTML = `${renderSortableHead(cols)}<tbody>${body}</tbody>`;
}

const BEST_SHAPE_BY_VENDOR_JS = { amd: "e6-standard-ax", intel: "x12-standard-ax", arm: "a4-standard-ax" };

function familySelectHtml(row) {
  const cur = normalizeVendorKey(row.shapeUsed?.vendor) || "amd";
  const opts = [["amd", "AMD"], ["intel", "Intel"], ["arm", "Arm"]]
    .map(([v, l]) => `<option value="${v}" ${v === cur ? "selected" : ""}>${l}</option>`)
    .join("");
  return `<select class="cell-select" data-shape-row="${escapeHtml(String(row.rowId))}" data-shape-kind="family">${opts}</select>`;
}

function shapeSelectHtml(row) {
  const vendor = normalizeVendorKey(row.shapeUsed?.vendor) || "amd";
  const cur = row.shapeUsed?.key;
  const shapes = (state.rateCards || []).filter((s) => normalizeVendorKey(s.processorVendor) === vendor);
  const list = shapes.length ? shapes : state.rateCards || [];
  const opts = list
    .map((s) => `<option value="${escapeHtml(s.key)}" ${s.key === cur ? "selected" : ""}>${escapeHtml(s.shortLabel || s.label)}</option>`)
    .join("");
  return `<select class="cell-select" data-shape-row="${escapeHtml(String(row.rowId))}" data-shape-kind="shape">${opts}</select>`;
}

// Converted OCI BOM: a per-server compute VM carries an editable OCI shape. Changing
// it re-prices that VM client-side (the BOM is already priced, so we don't round-trip
// the pricing engine).
function convertedShapeSelectHtml(row) {
  if (!row.isConvertedCompute) return "";
  const list = state.rateCards || [];
  if (!list.length) return "";
  const cur = row.shapeUsed?.key;
  const opts = list
    .map((s) => `<option value="${escapeHtml(s.key)}" ${s.key === cur ? "selected" : ""}>${escapeHtml(s.shortLabel || s.label)}</option>`)
    .join("");
  return ` <select class="cell-select converted-shape-select" data-converted-shape="${escapeHtml(String(row.rowId))}" title="Re-map this server's VM to a different OCI shape (re-prices its compute)">${opts}</select>`;
}

function round2(n) {
  return Math.round((Number(n) || 0) * 100) / 100;
}

function recomputeConvertedTotals(pricing) {
  let monthly = 0, ocpus = 0, mem = 0, blk = 0, fil = 0;
  for (const r of pricing.rows) {
    monthly += Number(r.monthly || 0);
    ocpus += Number(r.specs?.ocpus || 0);
    mem += Number(r.specs?.memoryGb || 0);
    blk += Number(r.specs?.blockStorageGb || 0);
    fil += Number(r.specs?.fileStorageGb || 0);
  }
  pricing.totals.monthly = round2(monthly);
  pricing.totals.annual = round2(monthly * 12);
  pricing.totals.fullServiceMonthly = round2(monthly);
  pricing.totals.ocpus = round2(ocpus);
  pricing.totals.memoryGb = round2(mem);
  pricing.totals.blockStorageGb = round2(blk);
  pricing.totals.fileStorageGb = round2(fil);
}

// Mutate one converted compute VM row to a shape (no re-render).
function applyShapeToVm(row, shape) {
  if (!row || !row.isConvertedCompute || !shape) return;
  const hours = Number(row.computeHours || 730);
  const ocpu = Number(row.originalOcpus || row.specs?.ocpus || 0);
  const mem = Number(row.originalMemoryGb || row.specs?.memoryGb || 0);
  const cRate = Number(shape.computeRate || 0);
  const mRate = Number(shape.memoryRate || 0);
  const ocpuMonthly = round2(ocpu * hours * cRate);
  const memMonthly = round2(mem * hours * mRate);
  const lbl = shape.shortLabel || shape.label;
  row.lineItems = [
    { sku: shape.computeSku || "", description: `OCI Compute ${lbl} - OCPU`, quantity: ocpu,
      unit: "OCPU Per Hour", rate: cRate, monthly: ocpuMonthly,
      mapping: `Re-mapped to ${shape.label}: ${ocpu} OCPU x ${hours} hrs x $${cRate}/OCPU-hr.` },
    { sku: shape.memorySku || "", description: `OCI Compute ${lbl} - Memory`, quantity: mem,
      unit: "Gigabyte Per Hour", rate: mRate, monthly: memMonthly,
      mapping: `Re-mapped to ${shape.label}: ${mem} GB x ${hours} hrs x $${mRate}/GB-hr.` },
  ];
  row.monthly = round2(ocpuMonthly + memMonthly);
  row.annual = round2(row.monthly * 12);
  row.shapeUsed = shape;
  row.specs.ocpus = ocpu;
  row.specs.memoryGb = mem;
  row.ociProduct = `OCI Compute VM — ${lbl} (${ocpu} OCPU / ${mem} GB)`;
  if (row.fullServiceMapping) row.fullServiceMapping.ociProduct = row.ociProduct;
}

function repriceConvertedCompute(rowId, shapeKey) {
  const pricing = state.pricing;
  if (!pricing || !pricing.converted) return;
  const row = pricing.rows.find((r) => String(r.rowId) === String(rowId));
  const shape = (state.rateCards || []).find((s) => s.key === shapeKey);
  if (!row || !shape) return;
  applyShapeToVm(row, shape);
  recomputeConvertedTotals(pricing);
  renderPricing(pricing);
  renderResults(pricing);
}

// Set EVERY converted compute VM to one shape (used by the page-3 shape picker so a
// converted BOM prices its compute on the shape you choose there). Returns count.
function applyBulkVmShape(shapeKey) {
  const pricing = state.pricing;
  if (!pricing || !pricing.converted) return 0;
  const shape = (state.rateCards || []).find((s) => s.key === shapeKey);
  if (!shape) return 0;
  let n = 0;
  for (const row of pricing.rows) {
    if (row.isConvertedCompute) { applyShapeToVm(row, shape); n += 1; }
  }
  recomputeConvertedTotals(pricing);
  return n;
}

document.addEventListener("change", (event) => {
  const sel = event.target.closest("[data-converted-shape]");
  if (!sel) return;
  repriceConvertedCompute(sel.dataset.convertedShape, sel.value);
});

function applyShapeOverride(rowId, kind, value) {
  if (!rowId) return;
  if (kind === "family") {
    const vendor = normalizeVendorKey(value) || "amd";
    const shapes = (state.rateCards || []).filter((s) => normalizeVendorKey(s.processorVendor) === vendor);
    const def = shapes.find((s) => s.key === BEST_SHAPE_BY_VENDOR_JS[vendor]) || shapes[0];
    if (def) state.shapeOverrides[rowId] = def.key;
  } else {
    state.shapeOverrides[rowId] = value;
  }
  priceRows({ keepView: true });
}

function flagActive(row) {
  return Boolean(row.mappingFlag) && !state.approvedFlags[row.rowId];
}

// Show the OCI shape an EC2/compute row was mapped to (e.g. "E6 Standard Ax").
// Only compute rows (those sized with OCPUs) carry a flex shape; storage/DBaaS/
// networking rows don't, so they get no badge.
function computeShapeBadge(row) {
  const ocpus = Number(row.specs?.ocpus || 0);
  if (ocpus <= 0) return "";
  const shape = row.shapeUsed?.shortLabel || row.shapeUsed?.label;
  if (!shape) return "";
  return ` <span class="shape-map-badge" title="OCI shape mapped for this compute line">${escapeHtml(shape)}</span>`;
}

function mappingFlagBadge(row) {
  if (row.costAction === "remove") {
    return ` <span class="size-flag size-flag-removed" title="Removed from both sides of the BOM">REMOVED</span>`;
  }
  if (row.costAction === "carry") {
    return ` <span class="size-flag size-flag-carried" title="OCI cost set equal to the source AWS cost">CARRIED OVER</span>`;
  }
  if (state.approvedFlags[row.rowId]) {
    return ` <span class="size-flag size-flag-approved" title="Mapping approved">✓ approved</span>`;
  }
  if (row.mappingFlag) {
    let html = ` <span class="size-flag size-flag-review flag-clickable" data-flag-row="${escapeHtml(String(row.rowId))}" title="Click to approve this mapping">⚠ ${escapeHtml(row.mappingFlag)}</span>`;
    if (String(state.flagMenuRow) === String(row.rowId)) {
      html += ` <button type="button" class="flag-approve-btn" data-approve-row="${escapeHtml(String(row.rowId))}">Approve mapping</button>`;
    }
    return html;
  }
  return "";
}

function costActionSelectHtml(row) {
  const cur = row.costAction || "estimate";
  const opts = [
    ["estimate", "Use OCI estimate"],
    ["carry", "Carry over AWS cost"],
    ["remove", "Remove from BOM"],
  ].map(([v, l]) => `<option value="${v}" ${v === cur ? "selected" : ""}>${l}</option>`).join("");
  return `<select class="cell-select cost-action-select" data-cost-row="${escapeHtml(String(row.rowId))}">${opts}</select>`;
}

function applyCostOverride(rowId, value) {
  if (!rowId) return;
  if (value === "estimate" || !value) delete state.costOverrides[rowId];
  else state.costOverrides[rowId] = value;
  priceRows({ keepView: true });
}

function sizeFlagBadge(row) {
  const badges = [];
  const check = row.sizeCheck || {};
  if (check.status === "impossible") {
    badges.push(` <span class="size-flag size-flag-impossible" title="${escapeHtml(check.message || "")}">IMPOSSIBLE</span>`);
  } else if (check.status === "baremetal") {
    badges.push(` <span class="size-flag size-flag-baremetal" title="${escapeHtml(check.message || "")}">BARE METAL</span>`);
  }
  if (row.rightsized) {
    const fromBits = [];
    if (row.originalOcpus) fromBits.push(`${formatNumber(row.originalOcpus)} OCPU`);
    if (row.originalMemoryGb) fromBits.push(`${formatNumber(row.originalMemoryGb)} GB`);
    const from = fromBits.length ? ` (from ${fromBits.join(" / ")})` : "";
    badges.push(` <span class="size-flag size-flag-rightsized" title="OCPU &amp; RAM trimmed for newer-generation efficiency${escapeHtml(from)}">RIGHTSIZED</span>`);
  }
  if (Array.isArray(row.lineItems) && row.lineItems.some((li) => li && li.isGpu)) {
    badges.push(` <span class="size-flag size-flag-gpu" title="Mapped to an OCI GPU shape">GPU</span>`);
  }
  return badges.join("");
}

function renderResultsTable(rows, fullServiceBeta = false, cloudBill = false) {
  // Source-service filter + bulk row actions are cloud-bill only.
  if (!cloudBill) {
    if (els.sourceFilterPanel) els.sourceFilterPanel.hidden = true;
    if (els.bulkActionBar) els.bulkActionBar.hidden = true;
  }
  if (cloudBill) {
    const columns = [
      {
        key: "select",
        label: "",
        selector: true,
        sortValue: () => 0,
        render: (row) => `<input type="checkbox" class="row-select" data-row-select="${escapeHtml(String(row.rowId))}" ${state.selectedRows[row.rowId] ? "checked" : ""} aria-label="Select row"/>`,
      },
      {
        key: "sourceService",
        label: "Source service",
        sortValue: (row) => rowSourceName(row),
        render: (row) => escapeHtml(rowSourceName(row)),
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
        render: (row) => escapeHtml(row.fullServiceMapping?.ociProduct || row.lineItems?.[0]?.description || "Needs review") + computeShapeBadge(row) + mappingFlagBadge(row),
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
        key: "costAction",
        label: "Cost action",
        sortValue: (row) => row.costAction || "",
        render: (row) => costActionSelectHtml(row),
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
    // Left-sidebar source-service filter (built from ALL rows so you can re-check).
    renderSourceFilter(rows);
    const filtered = rows.filter((r) => !state.hiddenSources[rowSourceName(r)]);
    // Default order: flagged ("may not be optimal") rows on top, then everything
    // by total cost on the bill (source cost) descending.
    const billCost = (r) => Number(r.sourceMonthlyCost || 0);
    const ordered = filtered.slice().sort((a, b) => {
      const fa = flagActive(a) ? 1 : 0;
      const fb = flagActive(b) ? 1 : 0;
      if (fa !== fb) return fb - fa;
      return billCost(b) - billCost(a);
    });
    renderResultTableFromColumns(ordered, columns);
    syncBulkBar();
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
        render: (row) => escapeHtml(row.fullServiceMapping?.ociProduct || row.lineItems?.[0]?.description || "Needs review") + convertedShapeSelectHtml(row),
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
      key: "region",
      label: "Region",
      sortValue: (row) => row.region || "",
      render: (row) => escapeHtml(row.region || "-"),
    },
    {
      key: "family",
      label: "Processor Family",
      sortValue: (row) => row.shapeUsed?.vendor || "",
      render: (row) => familySelectHtml(row),
    },
    {
      key: "shape",
      label: "OCI shape",
      sortValue: (row) => row.shapeUsed?.label || "",
      render: (row) => shapeSelectHtml(row),
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
      key: "hours",
      label: "Hrs/mo",
      sortValue: (row) => Number(row.hoursPerMonth || 0),
      render: (row) => formatNumber(row.hoursPerMonth || 730),
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
    // Approve an "may not be optimal" mapping (clears the flag for that row).
    const approveBtn = event.target.closest("[data-approve-row]");
    if (approveBtn) {
      state.approvedFlags[approveBtn.dataset.approveRow] = true;
      state.flagMenuRow = null;
      rerenderResultsTable();
      return;
    }
    // Click the flag badge to reveal the "Approve mapping" action.
    const flagBadge = event.target.closest("[data-flag-row]");
    if (flagBadge) {
      const rid = flagBadge.dataset.flagRow;
      state.flagMenuRow = String(state.flagMenuRow) === String(rid) ? null : rid;
      rerenderResultsTable();
      return;
    }
    const button = event.target.closest("[data-result-sort]");
    if (!button) return;
    const key = button.dataset.resultSort;
    const direction = state.resultSort.key === key && state.resultSort.direction === "asc" ? "desc" : "asc";
    state.resultSort = { key, direction };
    rerenderResultsTable();
  });
  // Editable shape / shape-family dropdowns -> set per-row override and re-price.
  els.resultsTable.addEventListener("change", (event) => {
    const shapeSel = event.target.closest("select[data-shape-row]");
    if (shapeSel) {
      applyShapeOverride(shapeSel.dataset.shapeRow, shapeSel.dataset.shapeKind, shapeSel.value);
      return;
    }
    const costSel = event.target.closest("select[data-cost-row]");
    if (costSel) {
      applyCostOverride(costSel.dataset.costRow, costSel.value);
      return;
    }
    // Per-row selection checkbox.
    const rowCb = event.target.closest("input[data-row-select]");
    if (rowCb) {
      const id = rowCb.dataset.rowSelect;
      if (rowCb.checked) state.selectedRows[id] = true;
      else delete state.selectedRows[id];
      syncBulkBar();
      return;
    }
    // Select-all (currently visible rows).
    if (event.target.id === "selectAllRows") {
      const visible = (state.pricing?.rows || []).filter((r) => !state.hiddenSources[rowSourceName(r)]);
      if (event.target.checked) visible.forEach((r) => { state.selectedRows[r.rowId] = true; });
      else visible.forEach((r) => { delete state.selectedRows[r.rowId]; });
      rerenderResultsTable();
    }
  });
}

// Source-service filter (left sidebar).
els.sourceFilterList?.addEventListener("change", (event) => {
  const cb = event.target.closest("input[data-source-name]");
  if (!cb) return;
  const name = cb.dataset.sourceName;
  if (cb.checked) delete state.hiddenSources[name];
  else state.hiddenSources[name] = true;
  rerenderResultsTable();
});
els.sourceFilterAll?.addEventListener("click", () => {
  state.hiddenSources = {};
  rerenderResultsTable();
});
els.sourceFilterNone?.addEventListener("click", () => {
  (state.pricing?.rows || []).forEach((r) => { state.hiddenSources[rowSourceName(r)] = true; });
  rerenderResultsTable();
});

// Bulk cost-action controls.
els.bulkApply?.addEventListener("click", async () => {
  const n = Object.keys(state.selectedRows).filter((id) => state.selectedRows[id]).length;
  if (!n) return;
  const overlay = document.querySelector("#tableLoadingOverlay");
  const text = document.querySelector("#tableLoadingText");
  if (text) text.textContent = `Applying to ${n} selected row${n === 1 ? "" : "s"}…`;
  if (overlay) overlay.hidden = false;
  // Let the overlay paint before the heavy re-price/re-render.
  await new Promise((r) => requestAnimationFrame(() => r()));
  try {
    await applyBulkCostAction(els.bulkCostAction ? els.bulkCostAction.value : "estimate");
  } finally {
    if (overlay) overlay.hidden = true;
  }
});
els.bulkClear?.addEventListener("click", () => {
  state.selectedRows = {};
  rerenderResultsTable();
});

const columnPickerBtn = document.querySelector("#columnPickerBtn");
const columnPickerMenu = document.querySelector("#columnPickerMenu");
function setColumnPickerOpen(open) {
  if (!columnPickerMenu) return;
  columnPickerMenu.hidden = !open;
  if (columnPickerBtn) {
    columnPickerBtn.textContent = open ? "Columns ▴" : "Columns ▾";
    columnPickerBtn.setAttribute("aria-expanded", String(open));
    columnPickerBtn.classList.toggle("is-open", open);
  }
}
columnPickerBtn?.addEventListener("click", (e) => {
  e.stopPropagation();
  setColumnPickerOpen(columnPickerMenu ? columnPickerMenu.hidden : false);
});
document.addEventListener("click", (e) => {
  if (columnPickerMenu && !columnPickerMenu.hidden && !e.target.closest("#columnPicker")) {
    setColumnPickerOpen(false);
  }
});

els.fileInput.addEventListener("change", () => {
  uploadFile(els.fileInput.files[0]).catch(setUploadingError);
});
els.selectedDocClear?.addEventListener("click", () => {
  state.lastUploadFile = null;
  if (els.fileInput) els.fileInput.value = "";
  showSelectedDoc(null);
});
els.switchToOnPrem?.addEventListener("click", () => {
  state.intakeMode = "on_prem";
  state.providerHint = "auto";
  state.fullServiceBeta = false;
  syncModeUi();
  if (els.inventoryNotice) els.inventoryNotice.hidden = true;
  if (state.lastUploadFile) uploadFile(state.lastUploadFile).catch(setUploadingError);
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
  // A dropped .json is a saved workflow, not a bill — route it to the loader.
  if (file && /\.json$/i.test(file.name)) {
    loadWorkflowFromFile(file);
    return;
  }
  uploadFile(file).catch(setUploadingError);
});

// The "Load previous BOM" area is also a drop target for workflow files.
const loadBomZone = document.querySelector(".load-prev-bom");
if (loadBomZone) {
  ["dragenter", "dragover"].forEach((ev) =>
    loadBomZone.addEventListener(ev, (e) => { e.preventDefault(); e.stopPropagation(); loadBomZone.classList.add("is-dragging"); }));
  ["dragleave", "drop"].forEach((ev) =>
    loadBomZone.addEventListener(ev, (e) => { e.preventDefault(); e.stopPropagation(); loadBomZone.classList.remove("is-dragging"); }));
  loadBomZone.addEventListener("drop", (e) => {
    const [file] = e.dataTransfer.files;
    if (file) loadWorkflowFromFile(file);
  });
}

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
function onPriceShapeClick() {
  // A converted BOM is already priced — the page-3 shape choice re-prices its compute
  // VMs on that shape (client-side); no pricing-engine round-trip.
  if (state.pricing && state.pricing.converted) {
    applyBulkVmShape(state.selectedShape);
    renderPricing(state.pricing);
    renderResults(state.pricing);
    showResultsPage();
    return;
  }
  priceRows();
}
els.priceShapeButton.addEventListener("click", onPriceShapeClick);
els.rerunPricing.addEventListener("click", priceRows);
els.hideGpuToggle?.addEventListener("change", (event) => {
  state.hideGpuPricing = event.target.checked;
});
els.hideWindowsToggle?.addEventListener("change", (event) => {
  state.hideWindowsPricing = event.target.checked;
});
// Compute optimization (Rightsize) is only meaningful on the Ax shapes and the regular E6
// — those are the only shapes with a defined OCPU/RAM reduction. For anything else it would
// do nothing, so the control is disabled rather than silently no-op.
function rightsizeEligible() {
  const key = String((selectedShape() || {}).key || "");
  return key.endsWith("-ax") || key === "e6-standard";
}
function syncRightsizeAvailability() {
  const ok = rightsizeEligible();
  document.querySelectorAll(".rightsize-switch").forEach((sw) => {
    sw.classList.toggle("is-disabled", !ok);
    sw.querySelectorAll("[data-rightsize]").forEach((b) => {
      b.disabled = !ok;
    });
    sw.title = ok
      ? sw.dataset.titleOn || sw.title
      : "Rightsize is only available for the Ax shapes and the regular E6 — those are the shapes with a defined OCPU/RAM optimization. Select an Ax or E6 shape to enable it.";
  });
  // Force back to 1-to-1 if the current shape can't be rightsized.
  if (!ok && state.rightsize) setRightsizeMode(false);
}
function setRightsizeMode(value) {
  // Guard: never turn rightsize on for an ineligible shape.
  if (value && !rightsizeEligible()) value = false;
  state.rightsize = value;
  document.querySelectorAll(".rightsize-switch .mode-opt").forEach((b) => {
    b.classList.toggle("is-active", (b.dataset.rightsize === "true") === value);
  });
}
els.rightsizeSwitches?.forEach((sw) => {
  sw.addEventListener("click", (event) => {
    const opt = event.target.closest("[data-rightsize]");
    if (!opt || opt.disabled) return;
    setRightsizeMode(opt.dataset.rightsize === "true");
  });
});

function setCpuUnit(value) {
  const v = ["auto", "vcpu", "ocpu"].includes(value) ? value : "auto";
  state.cpuUnit = v;
  document.querySelectorAll(".cpuunit-switch .mode-opt").forEach((b) => {
    b.classList.toggle("is-active", b.dataset.cpuunit === v);
  });
  updateCpuUnitHint();
  // Re-render the review table so the OCPUs column reflects the chosen unit.
  if ((state.fields || []).length) renderTable();
}
els.cpuUnitSwitches?.forEach((sw) => {
  sw.addEventListener("click", (event) => {
    const opt = event.target.closest("[data-cpuunit]");
    if (!opt) return;
    setCpuUnit(opt.dataset.cpuunit);
    // If we've already priced, re-price so results/export stay in sync.
    if (typeof priceRows === "function" && state.pricing) priceRows({ keepView: true });
  });
});

function setRampMonths(months) {
  const newMonths = Math.max(1, Math.min(60, Math.round(months)));
  const oldMonths = state.ramp.months || 36;
  if (newMonths === oldMonths) return;
  const factor = newMonths / oldMonths;
  state.ramp.months = newMonths;
  // Rescale existing dots so the curve shape is preserved over the new horizon.
  state.ramp.points = (state.ramp.points || []).map((point) => ({
    ...point,
    month: Math.min(newMonths, Math.max(1, Math.round(point.month * factor))),
  }));
  // Make sure the final dot lands on the last month at the ceiling.
  const sorted = state.ramp.points.slice().sort((a, b) => a.month - b.month);
  if (sorted.length) {
    sorted[sorted.length - 1].month = newMonths;
    sorted[sorted.length - 1].monthly = state.ramp.ceiling;
  }
  if (els.rampPeakMonth) els.rampPeakMonth.max = String(newMonths);
  document.querySelectorAll(".ramp-months-switch .mode-opt").forEach((b) => {
    b.classList.toggle("is-active", Number(b.dataset.rampMonths) === newMonths);
  });
  renderConsumptionRamp();
}
document.querySelector(".ramp-months-switch")?.addEventListener("click", (event) => {
  const opt = event.target.closest("[data-ramp-months]");
  if (!opt) return;
  setRampMonths(Number(opt.dataset.rampMonths));
});
els.hoursPerMonth?.addEventListener("change", (event) => {
  const v = Number(event.target.value);
  state.hoursPerMonth = v > 0 ? v : 730;
  if (!(v > 0)) event.target.value = 730;
  // The user edited hours -> treat it as an override that wins over per-row data hours.
  state.hoursOverride = true;
  // Per-hour added services (ECPU, OCPU, LB, port) follow the hours setting — re-price them.
  repriceExtraServices();
});
els.oicMessagePacks?.addEventListener("change", (event) => {
  let v = Math.round(Number(event.target.value));
  if (!(v >= 1)) v = 1;
  event.target.value = v;
  state.oicMessagePacks = v;
  // Message-pack sizing changes the OCI cost server-side (cloud-bill mode) — re-price
  // so the app view + export reflect the new Oracle Integration Cloud line.
  if (state.pricing) priceRows({ keepView: true });
});
function applyAutoUI() {
  // Grey out only the shape grid/detail (keep the processor picker clickable so you can switch back).
  if (els.shapeDropdown) els.shapeDropdown.classList.toggle("shape-auto-disabled", state.auto);
}
els.exportExcel?.addEventListener("click", () => exportToExcel("quick"));
els.exportFullBom?.addEventListener("click", () => exportToExcel("full"));

// Download ONLY the architecture diagram (PNG + editable .drawio, zipped) for this BOM.
async function downloadDiagram() {
  if (!state.pricing) {
    els.engineStatus.textContent = "Run \"Reprice estimate\" first, then download the diagram.";
    return;
  }
  const btn = els.downloadDiagram;
  const original = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "Rendering diagram…"; }
  els.engineStatus.textContent = "Rendering the OCI architecture diagram…";
  try {
    const res = await fetch("/api/diagram", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        fields: state.fields,
        rows: state.rows,
        shape: state.selectedShape,
        intakeMode: state.intakeMode,
        providerHint: state.providerHint,
        fullServiceBeta: state.fullServiceBeta,
        hideGpuPricing: state.hideGpuPricing,
        hideWindowsPricing: state.hideWindowsPricing,
        rightsize: state.rightsize,
        cpuUnit: state.cpuUnit,
        auto: state.auto,
        autoTier: state.autoTier,
        shapeOverrides: state.shapeOverrides,
        costOverrides: state.costOverrides,
        hoursPerMonth: state.hoursPerMonth,
        hoursOverride: state.hoursOverride,
        bomName: state.bomName || "",
      }),
    });
    if (!res.ok) {
      let msg = "Diagram build failed.";
      try { msg = (await res.json()).error || msg; } catch (e) { /* non-JSON */ }
      throw new Error(msg);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    const safe = (state.bomName || "OCI").trim().replace(/[\\/:*?"<>|]+/g, "_").replace(/\s+/g, "_") || "OCI";
    link.download = `${safe}_architecture.zip`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    els.engineStatus.textContent = `Diagram downloaded: ${link.download} (PNG + draw.io)`;
  } catch (error) {
    els.engineStatus.textContent = `Diagram download failed — ${error.message}`;
    console.error("diagram download failed", error);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = original; }
  }
}
els.downloadDiagram?.addEventListener("click", downloadDiagram);
els.exportJson?.addEventListener("click", exportWorkflowJson);
els.loadWorkflow?.addEventListener("click", () => els.loadWorkflowFile?.click());
els.loadPrevBom?.addEventListener("click", () => els.loadWorkflowFile?.click());
els.loadWorkflowFile?.addEventListener("change", (event) => {
  const file = event.target.files && event.target.files[0];
  loadWorkflowFromFile(file);
  event.target.value = "";
});

// Convert an alternate OCI BOM -> recognize SKUs -> load live into results.
function setConvertStatus(name, message, phase) {
  const el = els.convertBomStatus;
  if (!el) return;
  el.hidden = false;
  el.className = `load-workflow-status lws-${phase}`;
  el.querySelector(".lws-icon").textContent = phase === "ok" ? "✓" : phase === "error" ? "✕" : "⏳";
  el.querySelector(".lws-name").textContent = name || "";
  el.querySelector(".lws-state").textContent = message || "";
}
async function convertBomFromFile(file) {
  if (!file) return;
  const nm = file.name || "bom";
  const okExt = /\.(xlsx|xls|csv|tsv)$/i.test(nm);
  setConvertStatus(nm, okExt ? "converting…" : "not an .xlsx / .csv file", okExt ? "loading" : "error");
  if (!okExt) return;
  if (els.priceSpinner) {
    els.priceSpinner.querySelector(".price-spinner-text").textContent = "Converting OCI BOM…";
    els.priceSpinner.hidden = false;
  }
  try {
    const fd = new FormData();
    fd.append("file", file);
    const resp = await fetch("/api/convert-bom", { method: "POST", body: fd });
    const payload = await resp.json();
    if (!resp.ok) throw new Error(payload.error || "Could not convert this BOM.");
    // Load the converted pricing live into the app and jump to results (page 4).
    state.intakeMode = "on_prem";
    state.fullServiceBeta = true;
    state.fields = [];
    state.rows = payload.rows || [];
    if (Array.isArray(payload.rateCards)) state.rateCards = payload.rateCards;
    state.selectedShape = payload.selectedShape?.key || state.selectedShape;
    state.pricing = payload;
    // Don't seed the BOM name from the uploaded filename — the export name comes from
    // what the user actually types at the top, nothing else.
    // A converted BOM starts on the Shape page (page 3): pick a shape (or keep the
    // detected per-server shapes) and continue to results. Pages 2 & 3 are navigable.
    renderPricing(payload);
    renderResults(payload);
    showShapePage();
    const rec = payload.recognizedSkus || 0;
    const rev = payload.unrecognizedSkus || 0;
    setConvertStatus(nm, `converted — ${payload.rows.length} line items, ${rec} SKUs recognized${rev ? `, ${rev} for review` : ""}. Choose a shape →`, "ok");
  } catch (error) {
    setConvertStatus(nm, error.message || "conversion failed", "error");
  } finally {
    if (els.priceSpinner) els.priceSpinner.hidden = true;
  }
}
els.convertBomBtn?.addEventListener("click", () => els.convertBomFile?.click());
els.convertBomFile?.addEventListener("change", (event) => {
  const file = event.target.files && event.target.files[0];
  convertBomFromFile(file);
  event.target.value = "";
});
els.bomName?.addEventListener("input", (event) => {
  state.bomName = event.target.value;
});
els.ociDiscount?.addEventListener("input", (event) => {
  let v = Number(event.target.value);
  if (!(v >= 0)) v = 0;
  if (v > 100) v = 100;
  state.ociDiscount = v;
  // Reflect the discount immediately in the OCI total + ramp so the app matches
  // the printout (which applies the same discount).
  if (state.pricing) renderResults(state.pricing);
});

function renderCrossCloud() {
  const wrap = els.crossCloudResults;
  if (!wrap) return;
  const raw = state.pricing?.crossCloud;
  const ociMonthly = Number(state.pricing?.totals?.monthly || 0);
  if (!raw) {
    wrap.innerHTML = `<p class="cross-cloud-empty">Run a pricing estimate first to compare other clouds.</p>`;
    return;
  }
  // Support both the new {bestMatch, topTier} shape and the older flat shape.
  const hasModes = raw.bestMatch || raw.topTier;
  const cc = hasModes ? (state.crossCloudTopTier ? raw.topTier : raw.bestMatch) : raw;
  const bestTip = raw.cloudBillMode
    ? "Best match: your source cloud stays at its ACTUAL billed cost; the other cloud is estimated on the closest equivalent shape."
    : "Best match: price every workload on the closest equivalent shape, using your real source-cloud instance prices where known.";
  const topTip = raw.cloudBillMode
    ? "Top of the line: a what-if — re-estimate EVERY cloud (including your source bill) on each cloud's newest-generation shape. Non-compute services stay at billed cost."
    : "Top of the line: price every workload on each cloud's newest-generation shape.";
  const toggle = hasModes
    ? `<div class="mode-switch cross-cloud-switch" role="group" aria-label="Equivalent shape mode">
         <button type="button" class="mode-opt ${state.crossCloudTopTier ? "" : "is-active"}" data-cc-tier="best" title="${escapeHtml(bestTip)}">Best match</button>
         <button type="button" class="mode-opt ${state.crossCloudTopTier ? "is-active" : ""}" data-cc-tier="top" title="${escapeHtml(topTip)}">Top of the line</button>
       </div>`
    : "";
  const cards = [];
  cards.push(`
    <div class="cross-cloud-card cross-cloud-oci">
      <span class="cross-cloud-card-name">Oracle Cloud (this estimate)</span>
      <span class="cross-cloud-card-monthly">${formatCurrency(ociMonthly)}<small>/mo</small></span>
      <span class="cross-cloud-card-annual">${formatCurrency(ociMonthly * 12)}/yr</span>
    </div>
  `);
  const tier = state.crossCloudTopTier;
  const basisLabel = (v) => {
    if (v.basis === "actual bill") return "your actual billed cost";
    if (v.basis === "what-if: bill re-shaped on newest-gen") return "what-if: your bill re-shaped on newest-gen";
    if (v.carriedRows) return `compute estimated · ${v.carriedRows} services at billed cost`;
    if (v.liveRows) return `live AWS Price List API (${v.liveRows} priced live)`;
    if (tier) return "newest-generation equivalent shape";
    if (v.basis === "actual") return "from your source-cloud instances";
    if (v.basis === "mixed") return `${v.actualRows} actual · ${v.estimatedRows} equivalent`;
    return "equivalent shape match";
  };
  ["aws", "azure"].forEach((key) => {
    const v = cc[key];
    if (!v || !v.priced) return;
    const monthly = Number(v.monthlyTotal || 0);
    const delta = monthly - ociMonthly;
    const deltaLabel = ociMonthly > 0
      ? `${delta >= 0 ? "+" : "−"}${formatCurrency(Math.abs(delta))}/mo vs OCI`
      : "";
    // Reversed: other cloud cheaper than OCI (negative) = red; pricier = green.
    const deltaClass = delta >= 0 ? "cross-cloud-down" : "cross-cloud-up";
    cards.push(`
      <div class="cross-cloud-card">
        <span class="cross-cloud-card-name">${escapeHtml(v.label || key.toUpperCase())}</span>
        <span class="cross-cloud-card-monthly">${formatCurrency(monthly)}<small>/mo</small></span>
        <span class="cross-cloud-card-annual">${formatCurrency(Number(v.annualTotal || monthly * 12))}/yr</span>
        ${deltaLabel ? `<span class="cross-cloud-delta ${deltaClass}">${deltaLabel}</span>` : ""}
        <span class="cross-cloud-basis">${escapeHtml(basisLabel(v))}</span>
      </div>
    `);
  });
  const gcp = cc.gcp;
  if (gcp && !gcp.priced) {
    cards.push(`
      <div class="cross-cloud-card cross-cloud-muted">
        <span class="cross-cloud-card-name">${escapeHtml(gcp.label || "Google Cloud")}</span>
        <span class="cross-cloud-card-note">${escapeHtml(gcp.note || "Sizing only")}</span>
      </div>
    `);
  }
  const srcCloud = raw.sourceCloud;
  const srcName = srcCloud === "azure" ? "Azure" : "AWS";
  const note = raw.cloudBillMode
    ? (tier
        ? `Top-of-the-line (what-if): every cloud — including your ${srcName} bill — is re-estimated on that cloud's newest-generation equivalent shape, so you can see what the same workloads would cost re-shaped. Non-compute services (storage, data transfer, managed services) stay at their actual billed cost. For directional comparison only — not a quote.`
        : `Best match: your ${srcName} total is your actual billed cost — no estimate. The other cloud estimates compute line items against an equivalent shape and carries non-compute services at their billed cost. Switch to Top of the line to re-estimate your bill on newest-generation shapes. For directional comparison only — not a quote.`)
    : tier
    ? "Top-of-the-line mode prices every workload against each cloud's newest-generation equivalent shape (Linux baseline plus Windows licensing where detected). For directional comparison only — not a quote."
    : "Best-match mode uses your actual source-cloud shape prices where known, otherwise the closest equivalent shape on each cloud (Linux baseline plus Windows licensing where detected). For directional comparison only — not a quote.";
  wrap.innerHTML = `
    ${toggle ? `<div class="cross-cloud-toolbar">${toggle}</div>` : ""}
    <div class="cross-cloud-grid">${cards.join("")}</div>
    <p class="cross-cloud-note">${note}</p>
  `;
  wrap.querySelectorAll("[data-cc-tier]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.crossCloudTopTier = btn.dataset.ccTier === "top";
      renderCrossCloud();
    });
  });
}

els.crossCloudTile?.addEventListener("click", () => {
  const wrap = els.crossCloudResults;
  if (!wrap) return;
  const willShow = wrap.hidden;
  if (willShow) renderCrossCloud();
  wrap.hidden = !willShow;
  els.crossCloudTile.setAttribute("aria-expanded", String(willShow));
  els.crossCloudTile.classList.toggle("is-open", willShow);
});
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
  // If a cloud bill is already loaded, re-parse it with the chosen provider so
  // mapping uses the right cloud (no need to re-pick the file).
  if (state.intakeMode === "cloud_bill" && state.lastUploadFile) {
    uploadFile(state.lastUploadFile);
  }
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

// ===========================================================================
// "Add OCI services" panel — search the OCI catalog, size a service, add it to
// the BOM. Added services flow into the results total and both exports.
// ===========================================================================
// List (undiscounted) monthly of added services — used for the cart display.
function extraServicesMonthly() {
  return (state.extraServices || []).reduce((t, s) => t + Number(s.monthly || 0), 0);
}

// Effective monthly of added services after the OCI discount. Native OCI services are
// discounted; 3rd-party licensing (Windows, SQL Server) is charged at list.
function extraServicesEffective() {
  const d = (state.ociDiscount || 0) / 100;
  return (state.extraServices || []).reduce((t, s) => {
    const m = Number(s.monthly || 0);
    return t + (s.thirdParty ? m : m * (1 - d));
  }, 0);
}

async function fetchCatalog() {
  const q = state.catalog.query || "";
  const g = state.catalog.group || "";
  try {
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (g) params.set("group", g);
    const r = await fetch(`/api/catalog?${params.toString()}`);
    const d = await r.json();
    state.catalog.groups = d.groups || [];
    state.catalog.results = d.results || [];
  } catch (e) {
    state.catalog.results = [];
  }
  renderServiceChips();
  renderServiceResults();
}

function renderServiceChips() {
  if (!els.serviceChips) return;
  const chips = [{ group: "", count: 0, label: "All" }].concat(
    (state.catalog.groups || []).map((g) => ({ ...g, label: g.group })),
  );
  els.serviceChips.innerHTML = chips
    .map((c) => {
      const active = (state.catalog.group || "") === c.group ? " is-active" : "";
      const count = c.group ? ` <span class="chip-count">${c.count}</span>` : "";
      return `<button type="button" class="service-chip${active}" data-group="${escapeHtml(c.group)}">${escapeHtml(c.label)}${count}</button>`;
    })
    .join("");
}

function serviceCardHtml(e, i) {
  let fields = (e.fields || [])
    .map((f) => {
      const showAttr = f.showWhen
        ? ` data-showwhen-field="${escapeHtml(f.showWhen.field)}" data-showwhen-value="${escapeHtml(f.showWhen.value)}"`
        : "";
      const control = f.options
        ? `<select class="svc-input" data-idx="${i}" data-key="${escapeHtml(f.key)}">
             ${f.options.map((o) => `<option value="${escapeHtml(o.value)}"${o.value === f.default ? " selected" : ""}>${escapeHtml(o.label)}</option>`).join("")}
           </select>`
        : `<input type="number" class="svc-input" data-idx="${i}" data-key="${escapeHtml(f.key)}"
                  value="${f.default ?? 0}" min="${f.min ?? 0}" step="${f.step ?? 1}" />`;
      return `<label class="svc-field"${showAttr}><span>${escapeHtml(f.label)}</span>
                ${control}${f.unit ? `<em>${escapeHtml(f.unit)}</em>` : ""}</label>`;
    })
    .join("");
  // Per-hour services get an editable Hours/month input (defaults to 730).
  if (e.basis === "hour") {
    fields +=
      `<label class="svc-field"><span>Hours / month</span>
         <input type="number" class="svc-input" data-idx="${i}" data-key="__hours"
                value="730" min="1" step="1" />
         <em>hrs</em></label>`;
  }
  const rateTxt = `$${Number(e.rate).toLocaleString(undefined, { maximumFractionDigits: 4 })} / ${escapeHtml(e.unit)}`;
  return `
    <div class="service-card" data-idx="${i}">
      <div class="service-card-head">
        <div>
          <strong>${escapeHtml(e.name)}</strong>
          <span class="service-card-meta">${escapeHtml(e.group)} · ${escapeHtml(e.sku)} · ${rateTxt}</span>
        </div>
        <span class="service-card-cost" data-cost="${i}">$0.00/mo</span>
      </div>
      ${e.note ? `<p class="service-card-note">${escapeHtml(e.note)}</p>` : ""}
      <div class="service-card-fields">${fields}</div>
      <div class="service-card-actions">
        <button type="button" class="ghost-button svc-add" data-idx="${i}">Add to BOM</button>
      </div>
    </div>`;
}

function renderServiceResults() {
  if (!els.serviceResults) return;
  const items = state.catalog.results || [];
  if (!items.length) {
    els.serviceResults.innerHTML =
      `<p class="service-empty">${state.catalog.query ? "No services match that search." : "Pick a category or search to add services."}</p>`;
    return;
  }
  // Group results by category into collapsible sections. Remembering open/closed per group
  // means browsing stays tidy — expand only the category you care about.
  const groupsInOrder = [];
  const byGroup = new Map();
  items.forEach((e, i) => {
    if (!byGroup.has(e.group)) {
      byGroup.set(e.group, []);
      groupsInOrder.push(e.group);
    }
    byGroup.get(e.group).push({ e, i });
  });

  // Default open state: open everything on a text search or a single group; otherwise
  // start every category collapsed so the "All" list opens compact.
  const openState = state.catalog.groupsOpen || {};
  const singleOrSearch = groupsInOrder.length === 1 || !!state.catalog.query;

  els.serviceResults.innerHTML = groupsInOrder
    .map((g, gi) => {
      const entries = byGroup.get(g);
      const open = g in openState ? openState[g] : singleOrSearch;
      const cards = entries.map(({ e, i }) => serviceCardHtml(e, i)).join("");
      return `
        <section class="service-group${open ? " is-open" : ""}" data-group="${escapeHtml(g)}">
          <button type="button" class="service-group-head" data-group-toggle="${escapeHtml(g)}" aria-expanded="${open}">
            <span class="service-group-caret" aria-hidden="true">▸</span>
            <span class="service-group-title">${escapeHtml(g)}</span>
            <span class="service-group-count">${entries.length}</span>
          </button>
          <div class="service-group-body"${open ? "" : " hidden"}>${cards}</div>
        </section>`;
    })
    .join("");

  els.serviceResults.querySelectorAll(".service-card").forEach((card) => {
    updateCardCost(Number(card.dataset.idx));
  });
  applyCardFieldVisibility();
}

function cardValues(idx) {
  const vals = {};
  els.serviceResults
    .querySelectorAll(`.svc-input[data-idx="${idx}"]`)
    .forEach((inp) => {
      // Dropdowns carry a string value (e.g. workload/deployment); numeric inputs a number.
      vals[inp.dataset.key] = inp.tagName === "SELECT" ? inp.value : (Number(inp.value) || 0);
    });
  return vals;
}

// Show/hide conditional fields (data-showwhen-*) based on the current dropdown selection.
function applyCardFieldVisibility(scope) {
  (scope || els.serviceResults).querySelectorAll("[data-showwhen-field]").forEach((el) => {
    const card = el.closest(".service-card");
    const ctrl = card && card.querySelector(`.svc-input[data-key="${el.dataset.showwhenField}"]`);
    el.style.display = ctrl && ctrl.value === el.dataset.showwhenValue ? "" : "none";
  });
}

// Mirror of oci_catalog.line_cost so the preview is instant (server recomputes on add/export).
// Per-hour services use the app's hours-per-month setting, not a static 730.
function clientLineCost(entry, v) {
  const rate = Number(entry.rate || 0);
  const free = entry.free || {};
  // Add-ins default to 730 hours/month, editable per SKU via the "__hours" input.
  const hours = Number(v.__hours) > 0 ? Number(v.__hours) : 730;
  const cid = entry.id || entry.catalogId;
  if (cid === "block") {
    const gb = Number(v.gb || 0), vpus = Number(v.vpus || 10);
    return Math.round((gb * 0.0255 + gb * vpus * 0.0017) * 100) / 100;
  }
  if (cid === "fsdr") {
    // Full Stack DR: member OCPUs (compute+DB, both regions) + DB ECPUs + OIC packs.
    const ocpu = Number(v.p_compute || 0) + Number(v.p_db_ocpu || 0) + Number(v.s_compute || 0) + Number(v.s_db_ocpu || 0);
    const ecpu = Number(v.p_db_ecpu || 0) + Number(v.s_db_ecpu || 0);
    const oic = Number(v.p_oic || 0) + Number(v.s_oic || 0);
    return Math.round((ocpu * 0.0128 + ecpu * 0.0032 + oic * 0.192) * hours * 100) / 100;
  }
  if (cid === "adb") {
    // Autonomous AI Database: ECPU + storage + backup (mirror of oci_catalog.line_cost).
    const ecpuCost = Number(v.ecpu || 0) * 0.336 * hours;
    const bak = Number(v.bakgb || 0);
    if (String(v.deployment || "serverless") === "dedicated") {
      const infra = (Number(v.dbservers || 0) * 6.3014 + Number(v.storageservers || 0) * 5.4795) * hours;
      const backup = Math.max(0, bak - 10) * 0.0255;
      return Math.round((ecpuCost + infra + backup) * 100) / 100;
    }
    const storeRate = String(v.workload || "atp") === "adw" ? 0.0299 : 0.1953;
    return Math.round((ecpuCost + Number(v.dbgb || 0) * storeRate + bak * 0.0299) * 100) / 100;
  }
  if (cid === "desktops") {
    // Secure Desktops: per-desktop fee ($20) + compute + boot + optional block per desktop.
    // DVH (Windows-BYOL-on-DVH) runs on E4.128 host(s); VM modes use E6 per desktop.
    const n = Number(v.desktops || 0), ocpu = Number(v.ocpu || 0);
    let cost = n * 20.0
      + Number(v.optgb || 0) * n * 0.0255
      + Number(v.optgb || 0) * Number(v.optvpu || 0) * n * 0.0017;
    if (String(v.os || "linux") === "win_dvh") {
      const hosts = ocpu ? Math.max(1, Math.ceil(n * ocpu / 124)) : 1;
      cost += hosts * 128 * hours * 0.025 + hosts * 2048 * hours * 0.0015
        + Number(v.bootgb || 0) * hosts * 0.0255
        + Number(v.bootgb || 0) * Number(v.bootvpu || 0) * hosts * 0.0017;
    } else {
      cost += ocpu * n * hours * 0.03 + Number(v.memory || 0) * n * hours * 0.002
        + Number(v.bootgb || 0) * n * 0.0255
        + Number(v.bootgb || 0) * Number(v.bootvpu || 0) * n * 0.0017;
    }
    return Math.round(cost * 100) / 100;
  }
  if (cid === "sqllic") {
    // SQL Server license: per-edition OCPU-hour rate (Express is free).
    const ed = String(v.edition || "enterprise");
    const sqlRate = ed === "standard" ? 0.37 : ed === "express" ? 0 : 1.47;
    return Math.round(Number(v.ocpu || 0) * sqlRate * hours * 100) / 100;
  }
  if (cid === "kms") {
    // Key Management: vaults + external key mgmt + dedicated HSM (software keys free).
    return Math.round((Number(v.vaults || 0) * hours * 3.724
      + Number(v.external || 0) * 3.0
      + Number(v.hsm || 0) * hours * 1.75) * 100) / 100;
  }
  if (cid === "waf") {
    // WAF: instances (first free) + incoming requests per 1M (first 10M free).
    return Math.round((Math.max(0, Number(v.instances || 0) - 1) * 5.0
      + Math.max(0, Number(v.requests || 0) - 10) * 0.6) * 100) / 100;
  }
  if (cid === "object") {
    // Object Storage: GB (first 10 free) + requests per 10k (first 50k free).
    return Math.round((Math.max(0, Number(v.gb || 0) - 10) * 0.0255
      + Math.max(0, Number(v.requests || 0) - 5) * 0.0034) * 100) / 100;
  }
  if (cid === "pg") {
    // Database with PostgreSQL: managed OCPU + storage + underlying compute (per-processor) + VPU.
    const ocpu = Number(v.ocpu || 0), nodes = Number(v.nodes || 1) || 1, storage = Number(v.storage || 0);
    const intel = String(v.processor || "amd") === "intel";
    const cOcpu = intel ? 0.04 : 0.03, cMem = intel ? 0.0015 : 0.002;
    const cost = ocpu * nodes * hours * 0.098
      + storage * 0.072
      + ocpu * nodes * hours * cOcpu
      + Number(v.memory || 0) * nodes * hours * cMem
      + storage * Number(v.vpu || 0) * 0.0017;
    return Math.round(cost * 100) / 100;
  }
  if (cid === "mysql") {
    // MySQL HeatWave: ECPU + storage + backup + egress; HA triples ECPU+storage; +HeatWave.
    const mult = String(v.ha || "no") === "yes" ? 3 : 1;
    let cost = Number(v.ecpu || 0) * 0.0366 * hours * mult
      + Number(v.storage || 0) * 0.04 * mult
      + Number(v.backup || 0) * 0.04
      + Number(v.egress || 0) * 0.04;
    if (String(v.heatwave || "no") === "yes") {
      cost += Number(v.hwcapacity || 0) * 0.011 * hours + Number(v.hwstorage || 0) * 0.02;
    }
    return Math.round(cost * 100) / 100;
  }
  if (cid === "oic") {
    // Oracle Integration Cloud: auto-size message packs then × hours × per-edition rate.
    const oicRate = String(v.edition || "standard") === "enterprise" ? 1.2903 : 0.6452;
    const peak = Number(v.peakday || 0), monthly = Number(v.monthlymsgs || 0);
    let packs;
    if (peak > 0) packs = Math.ceil(peak / (24 * 5000));
    else if (monthly > 0) packs = Math.ceil(monthly / (hours * 5000));
    else packs = Number(v.packs || 0);
    return Math.round(packs * oicRate * hours * 100) / 100;
  }
  const fkey = entry.fields?.[0]?.key;
  let qty = fkey ? Number(v[fkey] || 0) : 0;
  if (fkey in free) qty = Math.max(0, qty - free[fkey]);
  const m = entry.basis === "hour" ? rate * qty * hours : rate * qty;
  return Math.round(m * 100) / 100;
}

// Re-price every already-added service when the hours setting changes, so the cart, the
// results total and the exports all stay on the same hours basis.
function repriceExtraServices() {
  (state.extraServices || []).forEach((s) => {
    s.monthly = clientLineCost(s, s.values || {});
  });
  renderServiceCart();
  renderServiceResults();
  refreshResultsTotals();
}

function updateCardCost(idx) {
  const entry = state.catalog.results[idx];
  if (!entry) return;
  const cost = clientLineCost(entry, cardValues(idx));
  const el = els.serviceResults.querySelector(`[data-cost="${idx}"]`);
  if (el) el.textContent = `${formatCurrency(cost)}/mo`;
}

function renderServiceCart() {
  if (!els.serviceCartList) return;
  const items = state.extraServices || [];
  els.serviceCartCount.textContent = String(items.length);
  els.serviceCartTotal.textContent = formatCurrency(extraServicesMonthly());
  if (!items.length) {
    els.serviceCartList.innerHTML = `<p class="service-empty">Nothing added yet.</p>`;
    return;
  }
  els.serviceCartList.innerHTML = items
    .map((s, i) => {
      const sizing = Object.entries(s.values || {})
        .map(([k, val]) => `${val} ${k}`)
        .join(" · ");
      return `
        <div class="cart-item">
          <div class="cart-item-main">
            <strong>${escapeHtml(s.name)}</strong>
            <span>${escapeHtml(sizing)}</span>
          </div>
          <span class="cart-item-cost">${formatCurrency(s.monthly)}/mo</span>
          <button type="button" class="cart-item-remove" data-remove="${i}" aria-label="Remove">✕</button>
        </div>`;
    })
    .join("");
}

function addServiceFromCard(idx) {
  const entry = state.catalog.results[idx];
  if (!entry) return;
  const values = cardValues(idx);
  const monthly = clientLineCost(entry, values);
  state.extraServices.push({
    catalogId: entry.id,
    name: entry.name,
    group: entry.group,
    sku: entry.sku,
    unit: entry.unit,
    basis: entry.basis,
    rate: entry.rate,
    free: entry.free || {},
    fields: entry.fields,
    thirdParty: !!entry.thirdParty || entry.group === "Licensing",
    values,
    monthly,
  });
  renderServiceCart();
  refreshResultsTotals();
  els.engineStatus.textContent = `Added ${entry.name} (${formatCurrency(monthly)}/mo) to the BOM.`;
}

// Re-render the KPI tiles + subtitle so an added service shows up in the total immediately,
// without a full server reprice.
function refreshResultsTotals() {
  if (state.pricing) renderResults(state.pricing);
}

// Add-OCI-services toggle is wired via a delegated document listener (see top of file)
// so it keeps working even if the results DOM is re-rendered.
if (els.serviceChips) {
  els.serviceChips.addEventListener("click", (e) => {
    const btn = e.target.closest(".service-chip");
    if (!btn) return;
    state.catalog.group = btn.dataset.group || "";
    state.catalog.groupsOpen = {};   // reset accordions to defaults for the new view
    fetchCatalog();
  });
}
if (els.serviceSearch) {
  let t = null;
  els.serviceSearch.addEventListener("input", (e) => {
    state.catalog.query = e.target.value.trim();
    clearTimeout(t);
    t = setTimeout(fetchCatalog, 200);
  });
}
if (els.serviceResults) {
  els.serviceResults.addEventListener("input", (e) => {
    if (e.target.classList.contains("svc-input")) {
      // A dropdown change can show/hide dependent fields (e.g. Serverless vs Dedicated).
      if (e.target.tagName === "SELECT") applyCardFieldVisibility(e.target.closest(".service-card"));
      updateCardCost(Number(e.target.dataset.idx));
    }
  });
  els.serviceResults.addEventListener("click", (e) => {
    const add = e.target.closest(".svc-add");
    if (add) {
      addServiceFromCard(Number(add.dataset.idx));
      return;
    }
    const head = e.target.closest(".service-group-head");
    if (head) {
      const g = head.dataset.groupToggle;
      const section = head.closest(".service-group");
      const body = section.querySelector(".service-group-body");
      const open = section.classList.toggle("is-open");
      head.setAttribute("aria-expanded", String(open));
      if (open) body.removeAttribute("hidden");
      else body.setAttribute("hidden", "");
      state.catalog.groupsOpen[g] = open;   // remember so re-render keeps your choice
    }
  });
}
if (els.serviceCartList) {
  els.serviceCartList.addEventListener("click", (e) => {
    const rm = e.target.closest(".cart-item-remove");
    if (!rm) return;
    state.extraServices.splice(Number(rm.dataset.remove), 1);
    renderServiceCart();
    refreshResultsTotals();
  });
}

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
