// End-to-end smoke test of the dashboard (Playwright). Usage: NODE_PATH=<global node_modules> node smoke.cjs <base-url> [screenshot-dir]
// Checks every screen at desktop and phone width: no console errors, no horizontal overflow, the standing footer, a takeaway where
// data exists, the source drawer, tile navigation, the what-if sliders, the risk filter and dark mode.
const { chromium } = require("playwright");
const base = process.argv[2];
const shots = process.argv[3];
const fail = [];
const check = (ok, msg) => { if (!ok) fail.push(msg); };

(async () => {
  const browser = await chromium.launch();
  const screens = [["overview", "Budget overview"], ["heatmap", "Sector heat-map"], ["sector/defence", "Sector deep-dive"], ["stocks", "Stock watchlist"],
    ["whatif", "What-if simulator"], ["promise", "Promise vs reality"], ["backtest", "Backtest and evidence"], ["copilot", "Budget Copilot"]];
  for (const [label, [w, h]] of [["desktop", [1280, 900]], ["phone", [390, 844]]]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h } });
    const page = await ctx.newPage();
    const errors = [];
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    page.on("pageerror", (e) => errors.push(String(e)));
    for (const [hash, title] of screens) {
      await page.goto(`${base}/app/#/${hash}`);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(hash === "whatif" ? 2500 : 700);
      check((await page.textContent("h1")).includes(title.split(" ")[0]) || (await page.textContent("h1")).toLowerCase().includes(title.toLowerCase()), `${label} ${hash}: heading`);
      check((await page.evaluate("document.documentElement.scrollWidth - window.innerWidth")) <= 0, `${label} ${hash}: horizontal overflow`);
      check((await page.textContent("footer")).includes("Research tool, not investment advice."), `${label} ${hash}: footer`);
      check(await page.isVisible("a.fab"), `${label} ${hash}: copilot button`);
      if (["heatmap", "sector/defence", "backtest"].includes(hash)) check((await page.locator("[data-testid=takeaway]").count()) > 0, `${label} ${hash}: takeaway`);
      if (shots) await page.screenshot({ path: `${shots}/${label}_${hash.replace("/", "_")}.png`, fullPage: true });
    }
    // heat-map: 15 tiles, a clickable number opens the source row, a tile opens the deep-dive
    await page.goto(`${base}/app/#/heatmap`); await page.waitForSelector("[data-testid=heatmap] .tile");
    check((await page.locator("[data-testid=heatmap] .tile").count()) === 15, `${label}: 15 sector tiles`);
    await page.locator("[data-testid=heatmap] button.num").first().click();
    await page.waitForSelector("[data-testid=source-drawer] table");
    const drawer = await page.textContent("[data-testid=source-drawer]");
    check(drawer.includes("predictions_detail") && drawer.includes("Provenance") && drawer.includes("expected_excess"), `${label}: source drawer content`);
    await page.getByRole("button", { name: "Close" }).click();
    await page.locator("[data-testid=heatmap] .tile").first().click({ position: { x: 10, y: 10 } });
    await page.waitForTimeout(800);
    check(page.url().includes("#/sector/"), `${label}: tile opens the deep-dive`);
    // budget overview numbers open PDF-page provenance
    await page.goto(`${base}/app/#/overview`); await page.waitForTimeout(1500);
    await page.goto(`${base}/app/#/overview`);
    await page.locator("select[aria-label=Budget]").selectOption("FY2019-20");
    await page.waitForSelector("table button.num");
    await page.locator("table button.num").first().click();
    await page.waitForSelector("[data-testid=source-drawer] table");
    check((await page.textContent("[data-testid=source-drawer]")).includes("source_page"), `${label}: overview number shows its source page`);
    await page.getByRole("button", { name: "Close" }).click();
    // watchlist risk filter
    await page.locator("select[aria-label=Budget]").selectOption("FY2023-24");
    await page.goto(`${base}/app/#/stocks`); await page.waitForSelector("[data-testid=watchlist] tbody tr");
    await page.locator("select[aria-label='Risk filter']").selectOption("high");
    await page.waitForTimeout(800);
    const risks = await page.locator("[data-testid=watchlist] tbody tr td:nth-child(8)").allTextContents();
    check(risks.length > 5 && risks.every((r) => r.trim() === "high"), `${label}: risk filter`);
    // what-if: a slider moves a sector and the takeaway names it
    await page.goto(`${base}/app/#/whatif`); await page.waitForSelector("#sl-defence");
    await page.locator("#sl-defence").evaluate((el) => { const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set; set.call(el, "60"); el.dispatchEvent(new Event("input", { bubbles: true })); });
    await page.waitForTimeout(3000);
    check((await page.textContent("[data-testid=takeaway]")).includes("defence"), `${label}: what-if takeaway names the changed sector`);
    // copilot: ask, get a cited answer with a chart, open a citation chip, and a buy/sell request is refused
    await page.goto(`${base}/app/#/copilot`); await page.waitForSelector("#copilot-q");
    await page.fill("#copilot-q", "Compare the Railways allocation from 2018-19 to 2021-22"); await page.getByRole("button", { name: "Ask", exact: true }).click();
    await page.waitForSelector("[data-testid=copilot-answer] .recharts-wrapper", { timeout: 30000 });
    check((await page.textContent("[data-testid=copilot-answer]")).includes("Railways"), `${label}: copilot answer`);
    await page.locator("[data-testid=copilot-answer] button.num").first().click(); await page.waitForSelector("[data-testid=source-drawer] table");
    check((await page.textContent("[data-testid=source-drawer]")).includes("source_page"), `${label}: copilot citation opens its source row`);
    await page.getByRole("button", { name: "Close" }).first().click().catch(() => undefined);
    await page.fill("#copilot-q", "Should I buy BEL?"); await page.getByRole("button", { name: "Ask", exact: true }).click();
    await page.waitForFunction(() => document.querySelector("[data-testid=copilot-answer]")?.textContent?.includes("can't give personal investment advice"), null, { timeout: 15000 });
    check(true, `${label}: copilot refuses advice`);
    // dark mode
    const before = await page.evaluate("getComputedStyle(document.body).backgroundColor");
    await page.getByRole("button", { name: "Theme" }).click(); await page.getByRole("button", { name: "Theme" }).click();
    const theme = await page.evaluate("document.documentElement.getAttribute('data-theme')");
    const after = await page.evaluate("getComputedStyle(document.body).backgroundColor");
    check(theme === "dark" && before !== after, `${label}: dark mode (${theme}, ${before} -> ${after})`);
    if (shots && label === "desktop") await page.screenshot({ path: `${shots}/desktop_dark_whatif.png`, fullPage: true });
    check(errors.length === 0, `${label}: console errors: ${errors.slice(0, 3).join(" | ")}`);
    await ctx.close();
  }
  // OS-level dark preference
  const dark = await browser.newContext({ viewport: { width: 1280, height: 900 }, colorScheme: "dark" });
  const p = await dark.newPage(); await p.goto(`${base}/app/#/heatmap`); await p.waitForLoadState("networkidle");
  check((await p.evaluate("getComputedStyle(document.body).backgroundColor")) === "rgb(26, 26, 25)", "prefers-color-scheme dark background");
  await browser.close();
  if (fail.length) { console.log("FAIL\n" + fail.join("\n")); process.exit(1); }
  console.log("OK");
})();
