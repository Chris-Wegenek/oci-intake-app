const path = require("node:path");
const { chromium } = require("playwright");

const ROOT = path.resolve(__dirname, "..");
const APP_URL = process.env.APP_URL || "http://127.0.0.1:8787";
const SAMPLE =
  process.env.SAMPLE_XLSX || "/Users/gus/Downloads/Current State Inventory (2).xlsx";

async function main() {
  const browser = await chromium.launch({ headless: true, channel: "chrome" });
  const page = await browser.newPage({ viewport: { width: 780, height: 900 } });
  try {
    await page.goto(APP_URL, { waitUntil: "domcontentloaded" });
    await page.setInputFiles("#fileInput", SAMPLE);
    await page.locator("#continueToReviewFromUpload:not(:disabled)").waitFor({ timeout: 120000 });
    await page.locator("#continueToReviewFromUpload").click();
    await page.locator("#reviewPanel:not(.is-hidden)").waitFor({ timeout: 120000 });
    await page.locator("#cpuUnitRow").screenshot({
      path: path.join(ROOT, "qa", "cpu-unit-spacing.png"),
    });
    await page.locator("#priceButton").click();
    await page.locator("#shapePage:not(.is-hidden)").waitFor();
    await page.locator("#priceShapeButton").click();
    await page.locator("#networkingPage:not(.is-hidden)").waitFor({ timeout: 120000 });
    await page.locator("#continueToPriceFromServices").click();
    await page.locator("#resultsPage:not(.is-hidden)").waitFor({ timeout: 120000 });
    await page.locator("#resultsTable tbody tr").nth(12).waitFor();

    await page.locator(".result-detail-wrap").scrollIntoViewIfNeeded();
    await page.locator(".result-detail-wrap").evaluate((wrap) => {
      wrap.scrollTop = 420;
      wrap.scrollLeft = 120;
    });
    await page.waitForTimeout(250);

    const metrics = await page.evaluate(() => {
      const wrap = document.querySelector(".result-detail-wrap");
      const header = document.querySelector("#resultsTable thead th:first-child");
      const cell = document.querySelector("#resultsTable tbody td:first-child");
      const headerRect = header.getBoundingClientRect();
      const cellRect = cell.getBoundingClientRect();
      const hit = document.elementFromPoint(
        headerRect.left + Math.min(50, headerRect.width / 2),
        headerRect.top + headerRect.height / 2,
      );
      return {
        scrollTop: wrap.scrollTop,
        scrollLeft: wrap.scrollLeft,
        header: {
          top: headerRect.top,
          bottom: headerRect.bottom,
          height: headerRect.height,
          zIndex: getComputedStyle(header).zIndex,
        },
        firstCell: {
          top: cellRect.top,
          bottom: cellRect.bottom,
          zIndex: getComputedStyle(cell).zIndex,
        },
        hit: {
          tag: hit?.tagName || "",
          className: hit?.className || "",
          text: hit?.textContent?.trim() || "",
          insideHeader: Boolean(hit?.closest("#resultsTable thead")),
        },
      };
    });
    if (!metrics.hit.insideHeader) {
      throw new Error(`Sticky header was painted over: ${JSON.stringify(metrics.hit)}`);
    }
    await page.locator(".result-detail-wrap").screenshot({
      path: path.join(ROOT, "qa", "scroll-header.png"),
    });
    console.log(JSON.stringify(metrics, null, 2));
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
