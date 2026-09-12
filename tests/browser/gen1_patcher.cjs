/* Actual Chromium file selection/apply/download and negative browser controls. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
(async () => {
  const executable = process.env.SLINK_CHROMIUM || chromium.executablePath();
  const context = await chromium.launchPersistentContext(path.join(config.output, 'profile'), {
    headless: true, acceptDownloads: true, downloadsPath: path.join(config.output, 'downloads'),
    viewport: { width: 1280, height: 1000 }, executablePath: executable
  });
  const page = await context.newPage();
  const deadline = setTimeout(() => {
    process.stderr.write('Browser gate exceeded its deadline.');
    context.close().finally(() => process.exit(1));
  }, 100000);
  const requests = []; const errors = []; const cases = [];
  page.on('request', request => requests.push({ method: request.method(), url: request.url(), body: request.postData() }));
  page.on('pageerror', error => errors.push(error.message));
  async function open(slug) { await page.goto(config.url + '/patcher?game=' + slug); await page.locator('#apply').waitFor(); }
  async function apply(file) { await page.locator('#rom-input').setInputFiles(file); await page.locator('#apply').click(); }
  async function refused(label) {
    await page.locator('#status.is-error').waitFor();
    assert.equal(await page.locator('#download').isVisible(), false);
    cases.push(label);
  }
  try {
    for (const target of config.targets) {
      await open(target.slug);
      const text = await page.locator('.patcher-features').innerText();
      assert(text.includes('Pokémon Center trade'));
      assert(!text.includes('Peer ghost') && !text.includes('Battle Calc'));
      if (target.variant === 'yellow') assert(!text.includes('START panel'));
      await apply(target.source);
      await page.locator('#download:not([hidden])').waitFor();
      assert((await page.locator('#status').innerText()).includes('verified fingerprint'));
      const [download] = await Promise.all([page.waitForEvent('download'), page.locator('#download').click()]);
      const file = path.join(config.output, target.slug + '-download.gbc');
      await download.saveAs(file);
      assert.equal(sha(fs.readFileSync(file)), target.final_sha256);
      await page.screenshot({ path: path.join(config.output, target.slug + '.png'), fullPage: true });
      cases.push(target.slug + ': exact downloaded final ROM');
      await apply(file); await refused(target.slug + ': reapply refused');
    }
    if (config.prepared) {
      await open(config.targets[0].slug);
      await apply(config.targets[1].source); await refused('other player input refused');
    } else {
    const red = config.targets.find(target => target.slug === 'rb-red');
    const blue = config.targets.find(target => target.slug === 'rb-blue');
    await open('rb-red'); await apply(blue.source); await refused('wrong title refused');
    const changed = Buffer.from(fs.readFileSync(red.source)); changed[changed.length - 1] ^= 1;
    const bad = path.join(config.output, 'changed.gb'); fs.writeFileSync(bad, changed);
    await apply(bad); await refused('modified input refused');
    await open('rb-red');
    await page.route('**/companion/SLink-Red.ups', async route => {
      const bytes = Buffer.from(fs.readFileSync(red.patch)); bytes[bytes.length - 1] ^= 1;
      await route.fulfill({ contentType: 'application/octet-stream', body: bytes });
    });
    await apply(red.source); await refused('changed patch refused');
    await page.unroute('**/companion/SLink-Red.ups');
    await open('rb-red');
    await page.evaluate(() => { document.querySelector('.patcher-wrap').dataset.patchedSha256 = '0'.repeat(64); });
    await apply(red.source); await refused('wrong final fingerprint refused without download');
    await open('rb-red');
    let release; let reached;
    const held = new Promise(resolve => { release = resolve; });
    const fetched = new Promise(resolve => { reached = resolve; });
    await page.route('**/companion/SLink-Red.ups', async route => {
      reached(); await held;
      await route.fulfill({ contentType: 'application/octet-stream', body: fs.readFileSync(red.patch) });
    });
    await apply(red.source); await fetched;
    await page.locator('#rom-input').setInputFiles(blue.source);
    release(); await page.unroute('**/companion/SLink-Red.ups', { behavior: 'wait' });
    await page.waitForFunction(() => document.querySelector('#status').textContent === 'Ready to patch.');
    assert.equal(await page.locator('#download').isVisible(), false);
    await page.locator('#apply').click(); await refused('stale async selection cannot publish old result');
    for (const fixture of config.codec) {
      const result = await page.evaluate(fixture => {
        try { window.SLinkPatcher.upsApply(new Uint8Array(fixture.source), new Uint8Array(fixture.patch)); return 'accepted'; }
        catch (error) { return error.message; }
      }, fixture);
      assert.notEqual(result, 'accepted'); assert(result.includes(fixture.expected), result);
      cases.push(fixture.name);
    }
    }
    assert.equal(errors.length, 0, JSON.stringify(errors));
    assert(requests.every(request => ['GET', 'HEAD'].includes(request.method) && request.body === null), 'ROM upload or mutation request occurred');
    fs.writeFileSync(path.join(config.output, 'result.json'), JSON.stringify({
      passed: true, cases, browser: context.browser().version(), playwright: require('playwright/package.json').version,
      node: process.version, browser_executable_sha256: sha(fs.readFileSync(executable)),
      page_errors: errors, requests, uploads: 0
    }, null, 2));
    process.stdout.write(JSON.stringify({ passed: true, cases: cases.length }));
  } finally { clearTimeout(deadline); await context.close(); }
})().catch(error => { process.stderr.write(error.stack); process.exitCode = 1; });
