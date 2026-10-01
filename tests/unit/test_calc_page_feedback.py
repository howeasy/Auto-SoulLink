"""Browser replay of the served calc bootstrap and the live profile bridge.

Requires Playwright, Chromium and an existing calc engine build. Source assets
override build assets exactly as server.calc_files.resolve does. No emulator.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DIST = Path(os.environ.get("SLINK_CALC_DIST", ROOT / "calc/dist"))


def _browser_prerequisites():
    if not (DIST / "calc/index.js").is_file():
        pytest.skip("calc build absent: build calc or set SLINK_CALC_DIST")
    node = shutil.which("node")
    if not node:
        pytest.skip("Node absent: required for calc browser replay")
    package_roots = [ROOT / "calc/node_modules", ROOT / "node_modules",
                     Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"]
    if os.environ.get("SLINK_NODE_PACKAGES"):
        package_roots.insert(0, Path(os.environ["SLINK_NODE_PACKAGES"]))
    packages = next((p for p in package_roots if (p / "playwright/package.json").is_file()), None)
    if not packages:
        pytest.skip("Playwright absent: install it or set SLINK_NODE_PACKAGES")
    chromium = os.environ.get("SLINK_CHROMIUM")
    if chromium:
        assert Path(chromium).is_file(), "SLINK_CHROMIUM points to a missing executable"
    return node, packages, chromium


def test_calc_live_profile_page_sequence():
    node, packages, chromium = _browser_prerequisites()
    script = r"""
const {chromium} = require(process.argv[1] + '/playwright');
const fs = require('fs'), path = require('path');
const root = process.argv[2], dist = process.argv[3];
const browserRoot = process.env.PLAYWRIGHT_BROWSERS_PATH || (process.platform === 'win32' ? path.join(process.env.LOCALAPPDATA,'ms-playwright') : path.join(process.env.HOME,'.cache/ms-playwright'));
const chrome = process.argv[4] || (fs.existsSync(browserRoot) ? fs.readdirSync(browserRoot).filter(n => /^chromium-/.test(n)).sort().reverse().flatMap(n => ['chrome-win64/chrome.exe','chrome-win/chrome.exe','chrome-linux/chrome','chrome-linux64/chrome','chrome-mac/Chromium.app/Contents/MacOS/Chromium'].map(p => path.join(browserRoot,n,p))).find(f => fs.existsSync(f)) : null) || chromium.executablePath();
if (!fs.existsSync(chrome)) {console.log(JSON.stringify({missing:'Chromium absent: install Playwright browsers or set SLINK_CHROMIUM'}));process.exit(0);}
const browser = await chromium.launch({headless:true,executablePath:chrome});
try {
  const page = await browser.newPage();
  const errors = [];
  const warnings = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => {if(m.type()==='warning') warnings.push(m.text());});
  const pure = {gen:1, dex:'purergb', name:'pureRGB', sets:{file:'PureRGB.js',var:'CUSTOMSETDEX_PURERGB'}};
  let profile = pure;
  let payload = () => ({calc:profile, a:{name:'Alice',party:[{species_name:'Pikachu', nickname:'Sparky',level:23,moves:['Thunderbolt','Quick Attack'],slot:1,showdown_paste:'Pikachu\nLevel: 23\n- Thunderbolt\n- Quick Attack'}]},b:{name:'Bob',party:[]}});
  await page.addInitScript(() => {
    localStorage.customsets = JSON.stringify({'Houndoom':{'Stale RR':{level:100,moves:['Dark Pulse']}}});
    window.EventSource = class extends EventTarget {constructor(){super();window.calcEvents=this;} close(){}};
  });
  await page.route('http://calc.test/**', async route => {
    const u = new URL(route.request().url());
    if (u.pathname.endsWith('/api/calc/mons')) return route.fulfill({json:payload()});
    if (u.pathname.endsWith('/api/events')) return route.fulfill({contentType:'text/event-stream',body:''});
    let rel = u.pathname.replace('/calc/', '');
    // Match server.calc_files.resolve: built HTML, current source JS, built engine.
    let file = path.join(root,'calc/src',rel);
    if (!fs.existsSync(file)) file = path.join(dist,rel);
    if (!fs.existsSync(file)) return route.fulfill({status:404,body:'missing '+rel});
    return route.fulfill({path:file,contentType:rel.endsWith('.js')?'application/javascript':rel.endsWith('.html')?'text/html':undefined});
  });
  const observations = [];
  for (const mode of ['normal','hardcore']) {
    await page.goto('http://calc.test/calc/'+mode+'.html?gen=9');
    await page.waitForFunction(() => document.querySelector('#slink-bridge-panel')?.textContent.includes('Sparky'));
    await page.waitForTimeout(100);
    observations.push(await page.evaluate(() => ({phase:'pure-'+location.pathname,gen,types:pokedex.Voltorb.types,title:document.querySelector('.title-text').textContent,documentTitle:document.title,mode:document.querySelector('.modeSelection').style.display,main:document.querySelector('#mainResult').textContent})));
    await page.locator('#slink-bridge-panel').getByText('Sparky / Pikachu',{exact:true}).click({timeout:3000});
    await page.waitForTimeout(100);
    observations.push(await page.evaluate(() => ({phase:'live-mon',level:$('#p1 .level').val(),move:$('#p1 .move1 select.move-selector').val(),label:$('#p1 .set-selector').select2('container').find('.select2-chosen').text(),main:$('#mainResult').text(),damage:damageResults[0][0].range(),description:damageResults[0][0].fullDesc('%')})));
    for (const next of [{gen:1,dex:'vanilla'},pure,{gen:9,dex:'rr'},pure]) {
      profile = next;
      await page.evaluate(() => {document.activeElement.blur();window.calcEvents.dispatchEvent(new Event('status'));});
      await page.waitForTimeout(400);
      observations.push(await page.evaluate(() => ({phase:'switch',gen,voltorb:pokedex.Voltorb.types,title:document.querySelector('.title-text').textContent,mode:document.querySelector('.modeSelection').style.display})));
    }
    profile = pure;
  }
  console.log(JSON.stringify({errors,warnings,observations}));
} finally {await browser.close();}
"""
    result = subprocess.run([node, "--input-type=module", "-e", "import {createRequire} from 'module'; const require=createRequire(import.meta.url);\n" + script,
                             str(packages), str(ROOT), str(DIST), chromium or ""], capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout.strip())
    if "missing" in data:
        pytest.skip(data["missing"])
    assert data["errors"] == [], data
    assert data["warnings"] == [], data
    for observation in data["observations"]:
        if observation["phase"].startswith("pure-"):
            assert observation["gen"] == 1, data
            assert observation["title"] == "Pokémon pureRGB Damage Calculator", data
            assert observation["documentTitle"] == observation["title"], data
            assert observation["types"] == ["Electric", "Fire"], data
            assert observation["mode"] == "none", data
            assert observation["main"] != "Loading...", data
        elif observation["phase"] == "live-mon":
            assert observation["level"] == "23", data
            assert observation["move"] == "Thunderbolt", data
            assert observation["label"] == "Pikachu (Sparky)", data
            assert "Pikachu" in observation["main"], data
            assert "Pikachu Thunderbolt" in observation["description"], data
            assert observation["damage"][1] >= observation["damage"][0] > 0, data
    switches = [item for item in data["observations"] if item["phase"] == "switch"]
    for offset in (0, 4):
        assert switches[offset]["gen"] == 1, data
        assert switches[offset]["voltorb"] == ["Electric"], data
        assert switches[offset + 1]["voltorb"] == ["Electric", "Fire"], data
        assert switches[offset + 2]["gen"] == 9, data
        assert switches[offset + 2]["mode"] == "", data
        assert switches[offset + 3]["gen"] == 1, data
        assert switches[offset + 3]["title"] == "Pokémon pureRGB Damage Calculator", data
