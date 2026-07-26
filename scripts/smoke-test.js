const path = require("node:path");
const fs = require("node:fs/promises");
const { chromium } = require("playwright");

const ROOT = path.resolve(__dirname, "..");
const QA_DIR = path.join(ROOT, "qa");
const SAMPLE = process.env.SAMPLE_XLSX || "/Users/gus/Downloads/Current State Inventory (2).xlsx";
const APP_URL = process.env.APP_URL || "http://127.0.0.1:8787";
const UPLOAD_TIMEOUT_MS = Number(process.env.UPLOAD_TIMEOUT_MS || 100000);
const PRICING_TIMEOUT_MS = Number(process.env.PRICING_TIMEOUT_MS || 100000);

async function main() {
  await fs.mkdir(QA_DIR, { recursive: true });

  const browser = await chromium.launch({
    headless: true,
    channel: "chrome",
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });

  await page.goto(APP_URL, { waitUntil: "domcontentloaded" });
  await page.screenshot({ path: path.join(QA_DIR, "landing.png"), fullPage: false });

  const navigationCheck = await browser.newPage({ viewport: { width: 1024, height: 768 } });
  await navigationCheck.goto(APP_URL, { waitUntil: "domcontentloaded" });
  await navigationCheck.getByRole("button", { name: "Step 4: Services" }).click();
  await navigationCheck.getByRole("heading", { name: "OCI services" }).waitFor();
  await navigationCheck.getByText("Upload inventory before building the complete estimate.", { exact: true }).waitFor();
  await navigationCheck.getByRole("button", { name: "Step 7: Architecture" }).click();
  await navigationCheck.getByRole("heading", { name: "Configure the OCI architecture" }).waitFor();
  await navigationCheck.getByText("Upload inventory before generating a diagram.", { exact: true }).waitFor();
  await navigationCheck.locator('[data-step="price"]').click();
  await navigationCheck.getByText("Upload inventory before viewing price.", { exact: true }).waitFor();
  await navigationCheck.setInputFiles("#fileInput", SAMPLE);
  await navigationCheck.getByText("Adjust your table", { exact: true }).waitFor({ timeout: UPLOAD_TIMEOUT_MS });
  await navigationCheck.locator('[data-step="price"]').click();
  await navigationCheck.getByText("OCI cost breakdown", { exact: true }).waitFor({ timeout: PRICING_TIMEOUT_MS });
  await navigationCheck.getByRole("button", { name: "Step 6: Compare" }).click();
  await navigationCheck.getByRole("heading", { name: "Estimate on other clouds" }).waitFor();
  await navigationCheck.locator("#crossCloudResults .cross-cloud-card").first().waitFor();
  await navigationCheck.getByRole("button", { name: "Back to price" }).click();
  await navigationCheck.getByText("OCI cost breakdown", { exact: true }).waitFor();
  await navigationCheck.close();

  await page.setInputFiles("#fileInput", SAMPLE);
  await page.getByText("Adjust your table", { exact: true }).waitFor({ timeout: UPLOAD_TIMEOUT_MS });
  await page.screenshot({ path: path.join(QA_DIR, "review.png"), fullPage: false });

  const rowCount = await page.locator("#rowCount").textContent();
  const columnCount = await page.locator("#columnCount").textContent();
  const parsedRows = Number(rowCount);
  const parsedColumns = Number(columnCount);
  if (parsedRows < 1 || parsedColumns < 4 || parsedColumns > 6) {
    throw new Error(`Unexpected parsed dimensions: rows=${rowCount}, columns=${columnCount}`);
  }

  await page.getByRole("button", { name: "Continue to shape" }).click();
  await page.getByText("Choose the OCI shape for this estimate", { exact: true }).waitFor({ timeout: 20000 });
  await page.locator("#shapeGrid button").first().waitFor({ timeout: 20000 });
  await page.screenshot({ path: path.join(QA_DIR, "shape.png"), fullPage: false });

  await page.getByRole("button", { name: "Continue to services" }).click();
  await page.getByRole("heading", { name: "OCI services" }).waitFor({ timeout: PRICING_TIMEOUT_MS });
  await page.locator("#serviceResults .service-group-head").first().waitFor({ timeout: 20000 });
  await page.screenshot({ path: path.join(QA_DIR, "networking.png"), fullPage: false });
  await page.getByRole("button", { name: "Continue to price" }).click();
  await page.getByText("OCI cost breakdown", { exact: true }).waitFor({ timeout: PRICING_TIMEOUT_MS });
  await page.locator("#resultsShape").waitFor({ timeout: 20000 });
  await page.locator("#resultsPage").getByText("Total Contract Value", { exact: true }).waitFor({ timeout: 20000 });
  await page.locator("#resultsKpis").getByText("Pricing summary", { exact: true }).waitFor({ timeout: 20000 });
  await page.locator("#resultsKpis").getByText("Specs identified", { exact: true }).waitFor({ timeout: 20000 });
  await page.screenshot({ path: path.join(QA_DIR, "pricing.png"), fullPage: false });

  const pricingText = await page.locator("#resultsPage").textContent();
  if (!/\$[\d,]+\.\d{2}/.test(pricingText)) {
    throw new Error("No formatted pricing total was visible after pricing.");
  }
  const rampHandles = page.locator("#rampChart .ramp-handle");
  if ((await rampHandles.count()) < 1) {
    throw new Error("The consumption ramp rendered without adjustable points.");
  }
  await rampHandles.first().click();
  const firstRampMonth = Number(await page.locator("#rampPeakMonth").inputValue());
  const firstRampMonthly = Number(await page.locator("#rampPeakMonthly").inputValue());
  if (firstRampMonth !== 1 || !(firstRampMonthly > 0)) {
    throw new Error(
      `Default ramp did not start in month 1: month=${firstRampMonth}, monthly=${firstRampMonthly}`,
    );
  }
  await page.locator("#rampChart").screenshot({ path: path.join(QA_DIR, "ramp.png") });

  await page.getByRole("button", { name: "Estimate on other clouds", exact: true }).click();
  await page.getByRole("heading", { name: "Estimate on other clouds" }).waitFor();
  await page.locator("#crossCloudResults .cross-cloud-card").first().waitFor();
  await page.screenshot({ path: path.join(QA_DIR, "other-clouds.png"), fullPage: false });
  await page.getByRole("button", { name: "Continue to architecture" }).click();
  await page.getByRole("heading", { name: "Configure the OCI architecture" }).waitFor({ timeout: PRICING_TIMEOUT_MS });
  await page.getByRole("heading", { name: "Export the diagram" }).waitFor({ timeout: 20000 });
  await page.locator("#primaryRegion").selectOption("us-ashburn-1");
  if (await page.locator("#splitAcrossADs").isDisabled()) {
    throw new Error("Availability Domain split stayed disabled for a three-AD region.");
  }
  await page.locator("#splitAcrossADsRow").click();
  if (!(await page.locator("#splitAcrossADs").isChecked())) {
    throw new Error("Availability Domain split did not turn on from the visible switch.");
  }
  await page.screenshot({ path: path.join(QA_DIR, "architecture.png"), fullPage: false });

  const architectureDownload = page.waitForEvent("download", { timeout: 120000 });
  await page.getByRole("button", { name: "Download architecture ZIP" }).click();
  const downloadedArchitecture = await architectureDownload;
  if (!downloadedArchitecture.suggestedFilename().endsWith("_architecture.zip")) {
    throw new Error(`Unexpected architecture download: ${downloadedArchitecture.suggestedFilename()}`);
  }
  await page.getByText(/Downloaded .*_architecture\.zip/).waitFor({ timeout: 20000 });
  await page.getByRole("button", { name: "Back to compare" }).click();
  await page.getByRole("heading", { name: "Estimate on other clouds" }).waitFor();

  const mobile = await browser.newPage({
    viewport: { width: 390, height: 844 },
    isMobile: true,
  });
  await mobile.goto(APP_URL, { waitUntil: "domcontentloaded" });
  await mobile.screenshot({ path: path.join(QA_DIR, "mobile-landing.png"), fullPage: false });
  await mobile.setInputFiles("#fileInput", SAMPLE);
  await mobile.getByText("Adjust your table", { exact: true }).waitFor({ timeout: UPLOAD_TIMEOUT_MS });
  await mobile.screenshot({ path: path.join(QA_DIR, "mobile-review.png"), fullPage: false });
  await mobile.getByRole("button", { name: "Continue to shape" }).click();
  await mobile.getByText("Choose the OCI shape for this estimate", { exact: true }).waitFor({ timeout: 20000 });
  await mobile.getByRole("button", { name: "Continue to services" }).click();
  await mobile.getByRole("heading", { name: "OCI services" }).waitFor({ timeout: PRICING_TIMEOUT_MS });
  await mobile.locator("#serviceResults .service-group-head").first().waitFor({ timeout: 20000 });
  await mobile.screenshot({ path: path.join(QA_DIR, "mobile-networking.png"), fullPage: false });
  await mobile.getByRole("button", { name: "Continue to price" }).click();
  await mobile.getByText("OCI cost breakdown", { exact: true }).waitFor({ timeout: PRICING_TIMEOUT_MS });
  await mobile.locator("#resultsPage").getByText("Total Contract Value", { exact: true }).waitFor({ timeout: 20000 });
  await mobile.locator("#resultsKpis").getByText("Pricing summary", { exact: true }).waitFor({ timeout: 20000 });
  await mobile.locator("#resultsKpis").getByText("Specs identified", { exact: true }).waitFor({ timeout: 20000 });
  await mobile.screenshot({ path: path.join(QA_DIR, "mobile-pricing.png"), fullPage: false });
  await mobile.getByRole("button", { name: "Step 6: Compare" }).click();
  await mobile.getByRole("heading", { name: "Estimate on other clouds" }).waitFor();
  await mobile.locator("#crossCloudResults .cross-cloud-card").first().waitFor();
  await mobile.screenshot({ path: path.join(QA_DIR, "mobile-other-clouds.png"), fullPage: false });
  await mobile.getByRole("button", { name: "Continue to architecture" }).click();
  await mobile.getByRole("heading", { name: "Configure the OCI architecture" }).waitFor({ timeout: PRICING_TIMEOUT_MS });
  await mobile.getByRole("button", { name: "Download architecture ZIP" }).waitFor({ timeout: 20000 });
  await mobile.screenshot({ path: path.join(QA_DIR, "mobile-architecture.png"), fullPage: false });

  await browser.close();
  console.log(
    JSON.stringify(
      {
        ok: true,
        url: APP_URL,
        rows: rowCount,
        columns: columnCount,
        screenshots: [
          "qa/landing.png",
          "qa/review.png",
          "qa/shape.png",
          "qa/networking.png",
          "qa/pricing.png",
          "qa/ramp.png",
          "qa/other-clouds.png",
          "qa/architecture.png",
          "qa/mobile-landing.png",
          "qa/mobile-review.png",
          "qa/mobile-networking.png",
          "qa/mobile-pricing.png",
          "qa/mobile-other-clouds.png",
          "qa/mobile-architecture.png",
        ],
      },
      null,
      2,
    ),
  );
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
