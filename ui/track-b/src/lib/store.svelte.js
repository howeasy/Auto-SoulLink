// Single reactive store, Svelte 5 runes. Fixtures live one directory up from the
// built bundle (server/static/mockups/fixtures/), so relative fetch keeps the whole
// thing path-agnostic.
import { capsFor, tri, hasHeldItems, romLabel } from './caps.js';

export const THEMES = [
  ['default', 'Default', '#070910'],
  ['light', 'Light', '#eef2fc'],
  ['transparent', 'Transparent', '#cccccc'],
  ['funtastic-grape', 'Grape', '#9933cc'],
  ['funtastic-jungle', 'Jungle', '#00cc66'],
  ['funtastic-fire', 'Fire', '#ff6600'],
  ['funtastic-ice', 'Ice', '#66ccff'],
  ['funtastic-watermelon', 'Watermelon', '#ff3366'],
  ['funtastic-smoke', 'Smoke', '#333333'],
];

export const TABS = ['Live', 'Links', 'Boxes', 'Memorial', 'Setup'];

function stored(key, fallback) {
  try { return localStorage.getItem(key) || fallback; } catch { return fallback; }
}

export const app = $state({
  gen: 'gen3',
  status: null,
  caps: null,
  runs: [],
  runId: null,
  tab: 'Live',
  theme: stored('slink-theme', 'default'),
  fontClassic: stored('slink-font', 'heading') === 'classic',
  density: stored('slink-density', 'comfortable'),
  loading: true,
  error: '',
});

const FIXTURES = '../fixtures/';

async function json(name) {
  const r = await fetch(FIXTURES + name, { cache: 'no-store' });
  if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
  return r.json();
}

export async function loadGen(gen) {
  app.loading = true;
  app.error = '';
  try {
    const [status, caps, runs] = await Promise.all([
      json(`${gen}.json`),
      app.caps ? Promise.resolve(app.caps) : json('capabilities.json'),
      app.runs.length ? Promise.resolve({ runs: app.runs }) : json('runs.json'),
    ]);
    app.gen = gen;
    app.status = status;
    app.caps = caps;
    app.runs = runs.runs;
    // The run rail is fixture data; the status payload belongs to whichever run is
    // selected. Gen 1 in the fixtures is the "Red vs Blue" run, Gen 3 the Kanto Duo.
    app.runId = gen === 'gen1' ? app.runs[2]?.run_id : app.runs[0]?.run_id;
  } catch (e) {
    app.error = String(e.message || e);
  } finally {
    app.loading = false;
  }
}

export function currentRun() {
  return app.runs.find((r) => r.run_id === app.runId) || null;
}

/**
 * Everything a panel needs about ONE player, resolved from that player's own
 * cartridge. Brief §5: nothing here may be hoisted to the run.
 */
export function playerCtx(side) {
  const p = app.status?.players?.[side] || null;
  const romType = p?.rom_type || '';
  const cr = capsFor(app.caps, romType);
  return {
    side,
    p,
    romType,
    label: romLabel(romType),
    capsFound: cr.found,
    capsInferred: cr.inferred,
    capsKey: cr.key,
    caps: cr.caps,
    abilities: tri(cr, 'abilities'),
    explode: tri(cr, 'explode_mode'),
    infoPanel: tri(cr, 'info_panel'),
    badges: cr.caps.badges || null,
    monsPerBox: tri(cr, 'mons_per_box'),
    statStageLabels: tri(cr, 'stat_stage_labels'),
    partyBlob: tri(cr, 'party_blob_size'),
    heldItems: p ? hasHeldItems(p) : false,
    party: p ? (p.party_keys || []).map((k) => ({ key: k, ...(p.party_details?.[k] || {}) })) : [],
  };
}

export function bothPlayers() {
  return ['a', 'b'].map(playerCtx);
}

export function applyTheme(name) {
  app.theme = name;
  const link = document.getElementById('slink-theme');
  if (link) link.href = `/static/themes/${name}.css`;
  document.body.className = document.body.className
    .split(/\s+/).filter((c) => c && !c.startsWith('theme-')).join(' ');
  document.body.classList.add(`theme-${name}`);
  document.body.classList.toggle('font-classic', app.fontClassic);
  try { localStorage.setItem('slink-theme', name); } catch { /* private mode */ }
}

export function applyFont(classic) {
  app.fontClassic = classic;
  document.body.classList.toggle('font-classic', classic);
  try { localStorage.setItem('slink-font', classic ? 'classic' : 'heading'); } catch { /* private mode */ }
}

export function applyDensity(d) {
  app.density = d;
  try { localStorage.setItem('slink-density', d); } catch { /* private mode */ }
}
