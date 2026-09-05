const { chromium } = require('playwright');
(async () => {
  const url = 'file:///' + process.argv[2].replace(/\/g, '/');
  const outDir = process.argv[3] || '.shots';
  const b = await chromium.launch();
  const errs = [];
  for (const [name, w, h] of [['desktop', 1440, 900], ['mobile', 390, 844]]) {
    const p = await b.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 2 });
    p.on('console', m => { if (m.type() === 'error') errs.push(`${name}: ${m.text()}`); });
    p.on('pageerror', e => errs.push(`${name}: ${e.message}`));
    await p.goto(url, { waitUntil: 'networkidle' });
    await p.waitForTimeout(1800);
    await p.screenshot({ path: `${outDir}/${name}-full.png`, fullPage: true });
    await p.screenshot({ path: `${outDir}/${name}-top.png` });
    const ov = await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    const font = await p.evaluate(() => getComputedStyle(document.body).fontFamily);
    console.log(`${name}: overflow=${ov}px  font=${font.split(',')[0]}`);
    await p.close();
  }
  await b.close();
  console.log(errs.length ? 'CONSOLE ERRORS:\n' + errs.join('\n') : 'no console errors');
})();
