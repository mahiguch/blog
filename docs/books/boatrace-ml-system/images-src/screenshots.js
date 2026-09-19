// boatrace-fun.net のスクリーンショット(第 15・16・17 章)。
// 実行: NODE_PATH=$(npm root -g) node screenshots.js [raceUrl]
//   (puppeteer がグローバルに無い場合は
//    NODE_PATH=$(npm root -g)/@mermaid-js/mermaid-cli/node_modules でも可)
// 出力: ../../../../images/boatrace-ml-system/{15-start-prediction,15-start-result,15-one-mark,16-ai-evaluation-chart,17-stats-page}.png
const path = require("path");
const puppeteer = require("puppeteer");

const OUT = path.resolve(__dirname, "../../../../images/boatrace-ml-system");
const RACE_URL = process.argv[2] || "https://boatrace-fun.net/race/2026-09-18/11/11";
const STATS_URL = "https://boatrace-fun.net/stats/";

// 見出しテキストに一致する要素の親(見出し + 図)を返す
async function sectionByHeading(page, tag, text) {
  const handle = await page.evaluateHandle(
    (tag, text) => {
      const h = Array.from(document.querySelectorAll(tag)).find((e) => e.textContent.trim() === text);
      return h ? h.parentElement : null;
    },
    tag,
    text,
  );
  const el = handle.asElement();
  if (!el) throw new Error(`section not found: <${tag}>${text}`);
  return el;
}

async function shot(el, name) {
  const file = path.join(OUT, `${name}.png`);
  await el.evaluate((e) => e.scrollIntoView({ block: "center" }));
  await el.screenshot({ path: file });
  console.log("wrote", file);
}

(async () => {
  const browser = await puppeteer.launch({ headless: true });
  const page = await browser.newPage();
  await page.setViewport({ width: 1100, height: 1000, deviceScaleFactor: 2 });

  // --- レース詳細ページ(第 15・16 章) ---
  await page.goto(RACE_URL, { waitUntil: "networkidle0" });
  console.log("race page:", RACE_URL);
  // 最初の予想者カード(本命予想)の 3 パネル
  await shot(await sectionByHeading(page, "h3", "スタート予想"), "15-start-prediction");
  await shot(await sectionByHeading(page, "h3", "1マーク予想"), "15-one-mark");
  await shot(await sectionByHeading(page, "h3", "AI 評価の内訳"), "16-ai-evaluation-chart");
  // レース結果内の「スタート(進入順)」(p + figure を含む div)
  await shot(await sectionByHeading(page, "p", "スタート（進入順）"), "15-start-result");

  // --- 統計ページ(第 17 章) ---
  await page.setViewport({ width: 1000, height: 1000, deviceScaleFactor: 2 });
  await page.goto(STATS_URL, { waitUntil: "networkidle0" });
  console.log("stats page:", STATS_URL);
  // 指示コメントの範囲(直前通算 → 累積回収率 → 本命予想 分析軸別)に絞る:
  // 累積的中率のカードと、2 人目以降の予想者セクション、フッターを非表示にする
  await page.evaluate(() => {
    const h2s = Array.from(document.querySelectorAll("h2"));
    const trend = h2s.find((h) => h.textContent.trim().startsWith("時系列推移"));
    if (trend) {
      const cards = trend.parentElement.querySelectorAll(":scope > div");
      if (cards[1]) cards[1].style.display = "none";
    }
    const axisSections = h2s.filter((h) => h.textContent.includes("分析軸別")).map((h) => h.parentElement);
    axisSections.slice(1).forEach((s) => (s.style.display = "none"));
    document.querySelectorAll("footer, nav").forEach((e) => (e.style.display = "none"));
  });
  const main = await page.evaluateHandle(() => document.querySelector("h1").parentElement);
  await shot(main.asElement(), "17-stats-page");

  await browser.close();
})();
