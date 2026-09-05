/* mockup.js — Track A data model for the merged SLink UI mockups.
 *
 * One Alpine component drives all three layouts. The layouts differ in ARRANGEMENT, not
 * in what they know, so they share this model completely and diverge only in markup.
 *
 * Every value comes from a fixture generated off the running server (see
 * docs/ui_mockup_brief.md §7). Nothing here invents data. Where the mockup shows a
 * number the real UI would show, it is the number the real /api/status produced.
 */

const FIXTURES = {
  gen3: { status: '../fixtures/gen3.json', label: 'Gen 3 — Radical Red' },
  gen1: { status: '../fixtures/gen1.json', label: 'Gen 1 — Red / Blue' },
};

/* Body-font candidates: [class, label, preview stack]. See fonts.css for why each is
 * here. The preview stack is applied to the chip itself, so the picker shows you the
 * face rather than describing it. */
const FONTS = [
  ['ui-plex', 'IBM Plex Sans', "'IBM Plex Sans', system-ui, sans-serif"],
  ['ui-inter', 'Inter', "'Inter', system-ui, sans-serif"],
  ['ui-grotesk', 'Space Grotesk', "'Space Grotesk', system-ui, sans-serif"],
  ['ui-plex-mono', 'IBM Plex Mono', "'IBM Plex Mono', ui-monospace, monospace"],
  ['ui-system', 'System UI', 'system-ui, sans-serif'],
  ['ui-pixelify', 'Pixelify (today)', "'Pixelify Sans', monospace"],
];

const THEMES = [
  ['default', 'Default', '#070910'],
  ['light', 'Light', '#eef2fc'],
  ['funtastic-grape', 'Grape', '#9933cc'],
  ['funtastic-jungle', 'Jungle', '#00cc66'],
  ['funtastic-fire', 'Fire', '#ff6600'],
  ['funtastic-ice', 'Ice', '#66ccff'],
  ['funtastic-watermelon', 'Watermelon', '#ff3366'],
  ['funtastic-smoke', 'Smoke', '#333333'],
];

/* Which run options each cartridge can actually honour, and why not when it cannot.
 *
 * The reasons are the interesting half. Today they live in `data-tip` prose on the
 * manager's checkboxes, which means the control is offered, looks enabled, and does
 * nothing — the player finds out by it not happening. Here the option is rendered in
 * place, greyed, carrying its reason, so "off" and "impossible" look different.
 *
 * `null` means "this cartridge decides at runtime" — for Gen 1 the native panel comes
 * from the companion patch, so it is a property of the player's ROM, not the game. */
const OPTION_SUPPORT = {
  species_lock: { all: true },
  gender_lock: {
    all: true,
    gen1_rby: { ok: false, why: 'Gen 1 has no gender mechanic, so the clause can never fire.' },
  },
  type_lock: { all: true },
  explode_mode: {
    all: false,
    why: 'Only the Radical Red client handles force_explode.',
    gen1_rby: { ok: true, why: 'No patch needed — Explosion is move 153 and the choice is a plain RAM write.' },
    gen3_frlge_rr: { ok: true },
  },
  rival_team_swap: {
    all: false,
    why: 'Needs the companion patch — gEnemyParty is encrypted.',
    gen1_rby: { ok: true, why: 'No patch needed — the Gen 1 enemy party is plaintext.' },
    gen3_frlge_rr: { ok: true },
  },
  overworld_presence: { all: false, why: 'Radical Red only.', gen3_frlge_rr: { ok: true } },
  native_messages: { all: false, why: 'Radical Red only.', gen3_frlge_rr: { ok: true } },
  native_sounds: {
    all: false,
    why: 'Radical Red only.',
    gen1_rby: { ok: false, why: 'The Gen 1 companion patch ships without audio: its only hook re-enters a non-reentrant sound routine.' },
    gen3_frlge_rr: { ok: true },
  },
  battle_calc: {
    all: false,
    why: 'Radical Red only.',
    gen1_rby: { ok: false, why: 'The calculator is pinned to modern mechanics and would misreport Gen 1 damage.' },
    gen3_frlge_rr: { ok: true },
  },
  pc_trade_npc: { all: false, why: 'Radical Red only.', gen3_frlge_rr: { ok: true } },
};

const OPTION_LABELS = {
  species_lock: 'Species Clause',
  gender_lock: 'Gender Clause',
  type_lock: 'Type Clause',
  explode_mode: 'Explode Mode',
  rival_team_swap: 'Rival Swap',
  overworld_presence: 'Overworld Presence',
  native_messages: 'Native Messages',
  native_sounds: 'Native Sounds',
  battle_calc: 'Battle Calc',
  pc_trade_npc: 'PC Trade NPC',
};

function mockup(initialLayout) {
  return {
    // ── state ────────────────────────────────────────────────────────────
    layout: initialLayout || 'l1',
    gen: 'gen3',
    dest: 'run',
    tab: 'live',
    theme: 'default',
    font: 'ui-plex',
    compact: false,
    debugOpen: false,
    loading: true,
    error: '',
    status: null,
    caps: {},
    runs: [],
    activeRunId: '',

    THEMES,
    FONTS,
    OPTION_LABELS,
    fixtureLabel() { return FIXTURES[this.gen].label; },

    // ── boot ─────────────────────────────────────────────────────────────
    async setup() {
      this.theme = localStorage.getItem('slink-theme') || 'default';
      this.applyTheme(this.theme);
      this.applyFont(localStorage.getItem('slink-mockup-font') || 'ui-plex');
      try {
        const [caps, runs] = await Promise.all([
          fetch('../fixtures/capabilities.json').then((r) => r.json()),
          fetch('../fixtures/runs.json').then((r) => r.json()),
        ]);
        this.caps = caps;
        this.runs = runs.runs || [];
        this.activeRunId = (this.runs.find((r) => r.status === 'running') || this.runs[0] || {}).run_id || '';
        await this.loadGen(this.gen);
      } catch (e) {
        // Surfaced rather than swallowed: opening these files off the filesystem instead
        // of through the server is the one way to break them, and the fix is a URL.
        this.error = String(e) + ' — serve this page over HTTP (python -m server.manager), not file://';
      }
      this.loading = false;
      this.watchSprites();
      window.addEventListener('keydown', (ev) => {
        if (ev.key === '`' && !/^(INPUT|TEXTAREA)$/.test(ev.target.tagName)) {
          this.debugOpen = !this.debugOpen;
        }
        if (ev.key === 'Escape') this.debugOpen = false;
      });
    },

    async loadGen(gen) {
      this.gen = gen;
      this.status = await fetch(FIXTURES[gen].status).then((r) => r.json());
    },

    /* slink.css hides funnotbun sprites until something chroma-keys their solid
     * background away (`img.mon-sprite[src*="funnotbun"]:not([data-bg-removed])`), so a
     * page that renders sprites without running that step shows blank cells and looks
     * like the data is missing. The vendored overlay-helpers.js already does the work and
     * exposes it as SLinkOverlay.processSprites; it runs once on DOMContentLoaded, which
     * is before Alpine has rendered anything. Re-run it whenever the DOM changes.
     *
     * Gen 1 hides the problem rather than avoiding it: its sprites come from PokeAPI,
     * are already transparent, and the CSS rule never matches them. */
    watchSprites() {
      const run = () => window.SLinkOverlay && window.SLinkOverlay.processSprites();
      let queued = false;
      new MutationObserver(() => {
        if (queued) return;
        queued = true;
        requestAnimationFrame(() => { queued = false; run(); });
      }).observe(document.body, { childList: true, subtree: true });
      run();
    },

    // ── theme / density ──────────────────────────────────────────────────
    applyTheme(slug) {
      this.theme = slug;
      document.getElementById('slink-theme').href = '/static/themes/' + slug + '.css';
      document.body.className = document.body.className
        .split(/\s+/).filter((c) => c && !c.startsWith('theme-')).concat('theme-' + slug).join(' ');
      localStorage.setItem('slink-theme', slug);
      this.syncDensity();
    },
    syncDensity() {
      document.body.classList.toggle('density-compact', this.compact);
    },

    /* Only --font-ui moves. --font-pixel stays Press Start 2P for the stream overlays,
     * where the text is large, sparse and read from across a room -- the argument is
     * about the dense UI, not about the brand. */
    applyFont(cls) {
      this.font = cls;
      document.body.classList.remove(...FONTS.map((f) => f[0]));
      document.body.classList.add(cls);
      localStorage.setItem('slink-mockup-font', cls);
    },

    // ── run + player accessors ───────────────────────────────────────────
    run() { return this.runs.find((r) => r.run_id === this.activeRunId) || this.runs[0] || {}; },
    runsByStatus(s) { return this.runs.filter((r) => r.status === s); },
    player(pid) { return (this.status && this.status.players[pid]) || {}; },

    /* The adapter key for a player's cartridge. Capabilities are per rom_type, not per
     * generation: `firered` and `firered_rr` answer differently on explode_mode and the
     * native panel because those come from the companion patch. */
    capsFor(pid) { return this.caps[this.player(pid).rom_type] || {}; },

    /* Whether BOTH cartridges can do something. A soul link is symmetric — a rule one
     * player cannot honour is not a rule the run has. */
    capBoth(key) {
      const a = this.capsFor('a')[key];
      const b = this.capsFor('b')[key];
      return a === true && b === true;
    },

    gameId(pid) { return this.capsFor(pid).game_id || ''; },

    /* Held items get no adapter predicate — see docs/ui_mockup_brief.md §4. Ask the data:
     * a column with nothing in it on either side is a column this run does not need. */
    anyHeldItems() {
      return ['a', 'b'].some((pid) =>
        Object.values(this.player(pid).party_details || {}).some((m) => m.held_item_id));
    },

    /* party_details is keyed BY mon key and the entries do not repeat it inside
     * themselves, so the key has to be carried in here or every downstream lookup —
     * which partner a slot is linked to, above all — silently matches nothing and the
     * whole party reads "unlinked". */
    party(pid) {
      const p = this.player(pid);
      return (p.party_keys || [])
        .map((k) => (p.party_details || {})[k] && { ...p.party_details[k], key: k })
        .filter(Boolean);
    },
    boxes(pid) { return this.player(pid).pc_boxes || []; },
    battle(pid) { return this.player(pid).battle_state || {}; },

    links() { return (this.status && this.status.links) || []; },
    linksBy(status) { return this.links().filter((l) => l.status === status); },
    killfeed() { return (this.status && this.status.killfeed) || []; },
    events(n) { return ((this.status && this.status.recent_events) || []).slice(0, n || 40); },

    /* Areas neither player may return to. Counted from area_states rather than from links,
     * because a dead zone can exist with no link in it at all — that is what it is. */
    deadZones() {
      const st = (this.status && this.status.area_states) || {};
      return Object.entries(st).filter(([, v]) => v === 'dead_zone').map(([k]) => k);
    },

    optionState(key) {
      const on = !!((this.status && this.status.rules) || {})[key];
      const rule = OPTION_SUPPORT[key] || { all: true };
      // Both players must be able to honour it, so take the more restrictive answer.
      let ok = true;
      let why = '';
      for (const pid of ['a', 'b']) {
        const gid = this.gameId(pid);
        const rr = (this.player(pid).rom_type || '').endsWith('_rr');
        const specific = rule[gid + (rr ? '_rr' : '')] || rule[gid];
        const decided = specific ? specific.ok : rule.all;
        if (!decided) {
          ok = false;
          why = (specific && specific.why) || rule.why || '';
          break;
        }
        if (specific && specific.why && !why) why = specific.why;
      }
      return { on, ok, why };
    },

    // ── display helpers ──────────────────────────────────────────────────
    hpPct(m) { return Math.max(0, Math.min(100, Math.round((m.hp / Math.max(m.maxHP, 1)) * 100))); },
    hpClass(m) { const p = this.hpPct(m); return p > 50 ? '' : p > 20 ? 'mid' : 'low'; },
    badgeCount(pid) {
      // A bitmask, not a count. The dashboard has been bitten by treating it as one.
      const mask = this.player(pid).badges || 0;
      return mask.toString(2).split('').filter((c) => c === '1').length;
    },
    badgeSlots(pid) { return (this.capsFor(pid).badges || []).length || 8; },
    statLabels(pid) {
      // null means the adapter in this checkout cannot answer, so fall back to the
      // seven-slot default rather than claiming Gen 1 has seven.
      return this.capsFor(pid).stat_stage_labels || ['ATK', 'DEF', 'SPD', 'SATK', 'SDEF', 'ACC', 'EVA'];
    },
    monsPerBox(pid) { return this.capsFor(pid).mons_per_box; },
    areaName(id) {
      const l = this.links().find((x) => x.area_id === id);
      if (l && l.area_display) return l.area_display;
      return id.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
    },
    shortTs(ts) { return (ts || '').slice(11, 19); },

    /* Pair a party slot with the partner it is soul-linked to. The spine in L2 and the
     * partner sub-line in L1 both need this, and it is the only place the two halves of
     * a link are joined for display. */
    linkFor(pid, key) {
      return this.links().find((l) => l[pid + '_key'] === key) || null;
    },
    partnerOf(pid, key) {
      const l = this.linkFor(pid, key);
      if (!l) return null;
      const o = pid === 'a' ? 'b' : 'a';
      return l[o + '_key'] ? { key: l[o + '_key'], nickname: l[o + '_nickname'], species_name: l[o + '_species_name'], level: l[o + '_level'], status: l.status } : null;
    },

    /* Rows for the L2 spine: one per link, newest catches last, so the two player columns
     * and the spine stay index-aligned. */
    boardRows() {
      return this.links().map((l) => ({
        area: l.area_display || this.areaName(l.area_id),
        status: l.status,
        a: l.a_key ? { key: l.a_key, nickname: l.a_nickname, species_name: l.a_species_name, level: l.a_level, sprite: l.a_sprite_html, shiny: l.a_shiny } : null,
        b: l.b_key ? { key: l.b_key, nickname: l.b_nickname, species_name: l.b_species_name, level: l.b_level, sprite: l.b_sprite_html, shiny: l.b_shiny } : null,
      }));
    },

    bondGlyph(status) { return status === 'alive' ? '<>' : status === 'dead' ? '><' : '..'; },
  };
}
