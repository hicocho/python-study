// 既存の Google Chrome を使ってスクリーンショットを撮る。
// Playwright MCP が繋がらないとき用。ブラウザバイナリの DL が要らない。
//
//   cd <scratchpad> && PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install --no-save playwright
//   node shot.js <url> <出力パス> [light|dark] [幅]
//
// PyScript のページは #loading が hidden になるまで待つ。
// playwright は scratchpad 側に入れるので、このファイルの隣ではなく
// 実行時のカレントディレクトリから解決する
const { createRequire } = require('module');
const path = require('path');
const { chromium } = createRequire(path.join(process.cwd(), 'noop.js'))('playwright');

(async () => {
  const [url, out, scheme = 'light', width = '480'] = process.argv.slice(2);
  const browser = await chromium.launch({ channel: 'chrome' });
  const page = await browser.newPage({
    colorScheme: scheme,
    viewport: { width: parseInt(width, 10), height: 1000 },
    deviceScaleFactor: 2,
  });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForFunction(
    () => !document.querySelector('#loading') || document.querySelector('#loading').hidden === true,
    { timeout: 60000 },
  ).catch(() => {});
  await page.screenshot({ path: out, fullPage: true });
  console.log('撮影:', out, '/ エラー:', errors.length ? errors : 'なし');
  await browser.close();
})();
