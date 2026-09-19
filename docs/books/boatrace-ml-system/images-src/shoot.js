// 使い方: NODE_PATH=$(npm root -g) node shoot.js in.html out.png [selector]
// HTML 内の要素(既定 #fig)を deviceScaleFactor=2 で撮る。
const puppeteer = require("puppeteer");
const path = require("path");
(async () => {
  const [input, output, selector = "#fig"] = process.argv.slice(2);
  const browser = await puppeteer.launch({ headless: "new", args: ["--disable-gpu", "--hide-scrollbars"] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1400, height: 1000, deviceScaleFactor: 2 });
  await page.goto("file://" + path.resolve(input), { waitUntil: "networkidle0" });
  await page.evaluate(() => document.fonts.ready);
  const el = await page.$(selector);
  await el.screenshot({ path: output, omitBackground: false });
  await browser.close();
})();
