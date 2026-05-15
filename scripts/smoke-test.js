const path = require("node:path");
const fs = require("node:fs/promises");
const { chromium } = require("playwright");

const ROOT = path.resolve(__dirname, "..");
const QA_DIR = path.join(ROOT, "qa");
const SAMPLE = "/Users/gus/Downloads/Current State Inventory (2).xlsx";
const APP_URL = process.env.APP_URL || "http://127.0.0.1:8787";

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
  await page.getByText("Review uploaded data", { exact: true }).waitFor({ timeout: 20000 });
  await page.screenshot({ path: path.join(QA_DIR, "review.png"), fullPage: false });

  const rowCount = await page.locator("#rowCount").textContent();
  const columnCount = await page.locator("#columnCount").textContent();
  if (rowCount !== "63" || columnCount !== "9") {
    throw new Error(`Unexpected parsed dimensions: rows=${rowCount}, columns=${columnCount}`);
  }

  await page.getByRole("button", { name: "Approve and price with LLM" }).click();
  await page.getByText("OCI cost breakdown", { exact: true }).waitFor({ timeout: 20000 });
  await page.locator("#resultsEngine").getByText("LLM-assisted", { exact: true }).waitFor({ timeout: 20000 });
  await page.locator("#resultsPage").getByText("$37,960.18", { exact: true }).waitFor({ timeout: 20000 });
  await page.screenshot({ path: path.join(QA_DIR, "pricing.png"), fullPage: false });

  const annualVisible = (await page.locator("#resultsPage").textContent()).includes("$455,522.16");
  if (!annualVisible) {
    throw new Error("Annual total was not visible after pricing.");
  }

  const mobile = await browser.newPage({
    viewport: { width: 390, height: 844 },
    isMobile: true,
  });
  await mobile.goto(APP_URL, { waitUntil: "domcontentloaded" });
  await mobile.screenshot({ path: path.join(QA_DIR, "mobile-landing.png"), fullPage: false });
  await mobile.setInputFiles("#fileInput", SAMPLE);
  await mobile.getByText("Review uploaded data", { exact: true }).waitFor({ timeout: 20000 });
  await mobile.screenshot({ path: path.join(QA_DIR, "mobile-review.png"), fullPage: false });
  await mobile.getByRole("button", { name: "Approve and price with LLM" }).click();
  await mobile.getByText("OCI cost breakdown", { exact: true }).waitFor({ timeout: 20000 });
  await mobile.locator("#resultsPage").getByText("$37,960.18", { exact: true }).waitFor({ timeout: 20000 });
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
