const path = require("node:path");
const fs = require("node:fs/promises");
const { chromium } = require("playwright");

const ROOT = path.resolve(__dirname, "..");
const APP_URL = process.env.APP_URL || "http://127.0.0.1:8787";
const QA_DIR = path.join(ROOT, "qa");
const CASES = new Set(
  (process.env.MATRIX_CASES || "aws,azure,workflow,state,converted")
    .split(",")
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean),
);
const FILES = {
  aws: process.env.AWS_BILL || "/Users/gus/Downloads/ecsv_5_2026 aws bill.csv",
  azure: process.env.AZURE_BILL || "/Users/gus/Downloads/Azure Bill no pricing159.xlsx",
  converted:
    process.env.CONVERTED_BOM ||
    "/Users/gus/Downloads/Brooks Automation AWS Bill Comparison (Oracle NumbervsAWS Total, License Included,gpu, no ebs)v2.xlsx",
  workflow: process.env.WORKFLOW_BOM || path.join(QA_DIR, "quick-bom.xlsx"),
  sample:
    process.env.SAMPLE_XLSX ||
    "/Users/gus/Downloads/Current State Inventory (2).xlsx",
};

const failures = [];

function monitor(page, label) {
  page.on("pageerror", (error) => failures.push(`${label} page error: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") {
      failures.push(`${label} console error: ${message.text()}`);
    }
  });
}

async function assertNoPageOverflow(page, label) {
  const overflow = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  if (overflow.scrollWidth > overflow.clientWidth + 1) {
    throw new Error(
      `${label} has horizontal page overflow: ${overflow.scrollWidth}px > ${overflow.clientWidth}px`,
    );
  }
}

async function openPage(browser, label, viewport = { width: 1366, height: 900 }) {
  const page = await browser.newPage({ viewport });
  monitor(page, label);
  await page.goto(APP_URL, { waitUntil: "domcontentloaded" });
  await page.locator("#uploadPanel").waitFor();
  return page;
}

async function uploadAndOpenReview(page, file) {
  await page.setInputFiles("#fileInput", file);
  await page.locator("#continueToReviewFromUpload:not(:disabled)").waitFor({ timeout: 180000 });
  await page.locator("#continueToReviewFromUpload").click();
  await page.locator("#reviewPanel:not(.is-hidden)").waitFor({ timeout: 180000 });
}

async function finishCloudBill(page, file, label) {
  await page.locator("#modeCloudBill").click();
  await uploadAndOpenReview(page, file);
  const rows = Number(await page.locator("#rowCount").textContent());
  if (!(rows > 0)) throw new Error(`${label} parsed zero rows.`);

  await page.locator("#priceButton").click();
  await page.locator("#shapePage:not(.is-hidden)").waitFor();
  await page.locator("#priceShapeButton").click();
  await page.locator("#networkingPage:not(.is-hidden)").waitFor({ timeout: 180000 });
  await page.locator("#continueToPriceFromServices").click();
  await page.locator("#resultsPage:not(.is-hidden)").waitFor({ timeout: 180000 });
  await page.locator("#resultsKpis").getByText("Pricing summary", { exact: true }).waitFor();
  const activeStep = await page.locator(".step.is-active").getAttribute("data-step");
  if (activeStep !== "price") {
    throw new Error(`${label} results loaded with the wrong active step: ${activeStep}`);
  }
  if (!/\$[\d,]+\.\d{2}/.test((await page.locator("#resultsPage").textContent()) || "")) {
    throw new Error(`${label} produced no formatted pricing total.`);
  }
  await assertNoPageOverflow(page, label);
  return rows;
}

async function testWorkflowReload(browser) {
  const page = await openPage(browser, "workflow reload");
  await page.setInputFiles("#loadWorkflowFile", FILES.workflow);
  await page.locator("#resultsPage:not(.is-hidden)").waitFor({ timeout: 180000 });
  await page.locator("#loadWorkflowStatus.lws-ok").waitFor({ state: "attached" });
  const activeStep = await page.locator(".step.is-active").getAttribute("data-step");
  if (activeStep !== "price") {
    throw new Error(`Workflow reload opened results with the wrong active step: ${activeStep}`);
  }
  if (await page.locator("#priceSpinner").isVisible()) {
    throw new Error("Workflow reload left the pricing spinner visible.");
  }
  await assertNoPageOverflow(page, "workflow reload");
  await page.screenshot({ path: path.join(QA_DIR, "matrix-workflow.png"), fullPage: false });
  await page.close();
}

async function testWorkflowStateRoundTrip(browser) {
  const exportPath = path.join(QA_DIR, "workflow-state-roundtrip.json");
  const source = await openPage(browser, "workflow state export");
  await uploadAndOpenReview(source, FILES.sample);
  const hoursInput = source.locator('#reviewTable input[type="number"]').first();
  const hoursFieldKey = await hoursInput.getAttribute("data-field-key");
  if (!hoursFieldKey) {
    throw new Error("Review did not expose a per-row Hours Running field.");
  }
  await hoursInput.fill("744");
  await source.locator('[data-cpuunit="ocpu"]').click();
  await source.locator(".review-filter-toggle").click();
  await source.locator("#priceButton").click();
  await source.locator("#shapePage:not(.is-hidden)").waitFor();
  await source.locator('[data-processor-vendor="arm"]').click();
  await source.locator('[data-processor-vendor="arm"].is-selected').waitFor();
  await source.locator("#hideSqlToggle").check({ force: true });
  await source.locator("#priceShapeButton").click();
  await source.locator("#networkingPage:not(.is-hidden)").waitFor({ timeout: 180000 });
  await source.locator("#continueToPriceFromServices").click();
  await source.locator("#resultsPage:not(.is-hidden)").waitFor({ timeout: 180000 });

  await source.locator("#exportMenuToggle").click();
  const downloadPromise = source.waitForEvent("download");
  await source.locator("#exportJson").click();
  const download = await downloadPromise;
  await download.saveAs(exportPath);
  const saved = JSON.parse(await fs.readFile(exportPath, "utf8"));
  const expected = {
    selectedVendor: "arm",
    hideSqlPricing: true,
    cpuUnit: "ocpu",
    hoursPerMonth: 730,
    hoursOverride: false,
    showMissingOnly: true,
  };
  for (const [key, value] of Object.entries(expected)) {
    if (saved[key] !== value) {
      throw new Error(`Workflow export lost ${key}: expected ${value}, received ${saved[key]}`);
    }
  }
  if (String(saved.rows?.[0]?.[hoursFieldKey]) !== "744") {
    throw new Error("Workflow export lost the first row's Hours Running value.");
  }
  await source.close();

  const restored = await openPage(browser, "workflow state restore");
  await restored.setInputFiles("#loadWorkflowFile", exportPath);
  await restored.locator("#resultsPage:not(.is-hidden)").waitFor({ timeout: 180000 });
  await restored.locator('[data-step="shape"]').click();
  await restored.locator("#shapePage:not(.is-hidden)").waitFor();
  if (!(await restored.locator('[data-processor-vendor="arm"]').getAttribute("class")).includes("is-selected")) {
    throw new Error("Workflow restore did not return to the Ampere processor family.");
  }
  if (!(await restored.locator("#hideSqlToggle").isChecked())) {
    throw new Error("Workflow restore lost the SQL licensing setting.");
  }
  if (await restored.locator("#hoursPerMonth, .hours-control-box").count()) {
    throw new Error("Workflow restore brought back the removed global hours control.");
  }
  await restored.locator('[data-step="review"]').click();
  await restored.locator("#reviewPanel:not(.is-hidden)").waitFor();
  if (!(await restored.locator('[data-cpuunit="ocpu"]').getAttribute("class")).includes("is-active")) {
    throw new Error("Workflow restore lost the CPU unit selection.");
  }
  if (!(await restored.locator("#missingOnlyToggle").isChecked())) {
    throw new Error("Workflow restore lost the missing-data filter.");
  }
  await restored.locator("#missingOnlyToggle").uncheck({ force: true });
  const restoredHours = restored.locator(
    `input[data-row-index="0"][data-field-key="${hoursFieldKey}"]`,
  );
  if ((await restoredHours.inputValue()) !== "744") {
    throw new Error("Workflow restore lost the first row's Hours Running value.");
  }
  await assertNoPageOverflow(restored, "workflow state restore");
  await restored.close();
}

async function testConvertedBom(browser) {
  const page = await openPage(browser, "alternate BOM conversion");
  await page.setInputFiles("#convertBomFile", FILES.converted);
  await page.locator("#shapePage:not(.is-hidden)").waitFor({ timeout: 180000 });
  await page.locator("#priceShapeButton").click();
  await page.locator("#networkingPage:not(.is-hidden)").waitFor({ timeout: 180000 });
  await page.locator("#continueToPriceFromServices").click();
  await page.locator("#resultsPage:not(.is-hidden)").waitFor({ timeout: 180000 });
  await page.locator("#resultsKpis").getByText("Pricing summary", { exact: true }).waitFor();
  await page.getByText("OCI BOM line details", { exact: true }).waitFor();
  await page.locator("#resultsTable thead").getByText("Line item", { exact: true }).waitFor();
  if (await page.locator("#resultsKpis").getByText("Specs identified", { exact: true }).count()) {
    throw new Error("Service-only converted BOM displayed an empty workload-spec section.");
  }
  await assertNoPageOverflow(page, "alternate BOM conversion");
  await page.screenshot({ path: path.join(QA_DIR, "matrix-converted-bom.png"), fullPage: false });
  await page.close();
}

async function main() {
  const browser = await chromium.launch({ headless: true, channel: "chrome" });
  const results = {};
  try {
    if (CASES.has("aws")) {
      const awsPage = await openPage(browser, "AWS cloud bill");
      results.awsRows = await finishCloudBill(awsPage, FILES.aws, "AWS cloud bill");
      await awsPage.screenshot({ path: path.join(QA_DIR, "matrix-aws.png"), fullPage: false });
      await awsPage.close();
    }
    if (CASES.has("azure")) {
      const azurePage = await openPage(browser, "Azure cloud bill");
      results.azureRows = await finishCloudBill(azurePage, FILES.azure, "Azure cloud bill");
      await azurePage.screenshot({ path: path.join(QA_DIR, "matrix-azure.png"), fullPage: false });
      await azurePage.close();
    }
    if (CASES.has("workflow")) await testWorkflowReload(browser);
    if (CASES.has("state")) await testWorkflowStateRoundTrip(browser);
    if (CASES.has("converted")) await testConvertedBom(browser);
  } finally {
    await browser.close();
  }

  if (failures.length) {
    throw new Error(failures.join("\n"));
  }
  console.log(JSON.stringify({ ok: true, url: APP_URL, ...results }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
