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
  await page.getByRole("button", { name: /E5 Standard/ }).click();
  await page.locator("#shapeRateTable").getByRole("cell", { name: "$0.0300" }).waitFor({ timeout: 20000 });
  await page.screenshot({ path: path.join(QA_DIR, "shape.png"), fullPage: false });

  await page.getByRole("button", { name: /Price (estimate|on OCI)/ }).click();
  await page.getByText("OCI cost breakdown", { exact: true }).waitFor({ timeout: PRICING_TIMEOUT_MS });
  await page.locator("#resultsPage").getByText("E5 Standard", { exact: true }).waitFor({ timeout: 20000 });
  await page.locator("#resultsPage").getByText("Total Contract Value", { exact: true }).waitFor({ timeout: 20000 });
  await page.screenshot({ path: path.join(QA_DIR, "pricing.png"), fullPage: false });

  const pricingText = await page.locator("#resultsPage").textContent();
  if (!/\$[\d,]+\.\d{2}/.test(pricingText)) {
    throw new Error("No formatted pricing total was visible after pricing.");
  }

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
  await mobile.getByRole("button", { name: /Price (estimate|on OCI)/ }).click();
  await mobile.getByText("OCI cost breakdown", { exact: true }).waitFor({ timeout: PRICING_TIMEOUT_MS });
  await mobile.locator("#resultsPage").getByText("Total Contract Value", { exact: true }).waitFor({ timeout: 20000 });
  await mobile.screenshot({ path: path.join(QA_DIR, "mobile-pricing.png"), fullPage: false });

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
          "qa/pricing.png",
          "qa/mobile-landing.png",
          "qa/mobile-review.png",
          "qa/mobile-pricing.png",
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
