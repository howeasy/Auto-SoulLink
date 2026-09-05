/* mockup.js — Track A data model for the merged SLink UI mockup.
 *
 * One Alpine component drives the page. Every value comes from a fixture generated off
 * the running server (see docs/ui_mockup_brief.md §7). Nothing here invents data: where
 * the mockup shows a number the real UI would show, it is the number /api/status
 * produced.
 *
 * The centre of the model is pairs(). A soul link's unit is the PAIR — two mons bound
 * across two cartridges, both of which die if either faints — and the payload hands the
 * two halves back separately: the bond in `links`, the live HP in each player's
 * `party_details`, the shelf in `pc_boxes`. pairs() joins them back into the thing the
 * player actually thinks about.
 */

const FIXTURES = {
  gen3: { status: '../fixtures/gen3.json', label: 'Gen 3 — Radical Red' },
  gen1: { status: '../fixtures/gen1.json', label: 'Gen 1 — Red / Blue' },
};

/* Body-font candidates: [class, label, preview stack]. See fonts.css. */
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

/* Which run options each cartridge can honour, and why not when it cannot. Today these
 * reasons live in data-tip prose on checkboxes that are offered, look enabled, and do
 * nothing. Here "off" and "impossible" look different. */
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

/* The three groups the manager's New-run form offers. Nothing is greyed here: at
 * creation there is no cartridge yet, so nothing is known to be impossible. The greying
 * happens on Setup once a player connects and the run learns what it is. */
const OPTION_GROUPS = [
  ['Link clauses', ['species_lock', 'gender_lock', 'type_lock']],
  ['Battle', ['explode_mode', 'rival_team_swap', 'overworld_presence']],
  ['Native UI', ['native_messages', 'native_sounds', 'battle_calc', 'pc_trade_npc']],
];

/* A pair is "at risk" when its weaker half is below this. Both halves die if either
 * faints, so the pair's health is its minimum, not its average. */
const RISK_PCT = 35;

const SECTION_LABELS = {
  pending: 'Pending link',
  linked: 'Linked',        // a stopped run: the bond is known, where each half sits is not
  party: 'In party',
  split: 'Split — one half boxed',
  boxed: 'Boxed',
  fallen: 'Fallen',
};

function mockup() {
  return {
    // ── state ────────────────────────────────────────────────────────────
    gen: 'gen3',
    dest: 'run',
    tab: 'board',
    theme: 'default',
    font: 'ui-plex',
    compact: false,
    debugOpen: false,
    launchersOpen: false,
    loading: true,
    error: '',
    fixture: null,       // the loaded /api/status payload
    caps: {},
    runs: [],
    activeRunId: '',
    pinnedRunId: '',
    draft: { name: '', opts: {} },

    THEMES,
    FONTS,
    OPTION_LABELS,
    OPTION_GROUPS,
    SECTION_LABELS,

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
        const running = this.runs.find((r) => r.status === 'running');
        this.activeRunId = (running || this.runs[0] || {}).run_id || '';
        this.pinnedRunId = running ? running.run_id : '';
        await this.loadGen(this.gen);
      } catch (e) {
        this.error = String(e) + ' — serve this page over HTTP (python -m server.manager), not file://';
      }
      this.loading = false;
      this.watchSprites();
      window.addEventListener('keydown', (ev) => {
        if (ev.key === '`' && !/^(INPUT|TEXTAREA)$/.test(ev.target.tagName)) this.debugOpen = !this.debugOpen;
        if (ev.key === 'Escape') { this.debugOpen = false; this.launchersOpen = false; }
      });
    },

    async loadGen(gen) {
      this.gen = gen;
      this.fixture = await fetch(FIXTURES[gen].status).then((r) => r.json());
    },

    /* slink.css hides funnotbun sprites until something chroma-keys their background
     * (`img.mon-sprite[src*="funnotbun"]:not([data-bg-removed])`). The vendored
     * overlay-helpers.js does the work; it runs on DOMContentLoaded, before Alpine has
     * rendered, so re-run it on every DOM change. setTimeout rather than rAF: rAF does
     * not fire in a background tab and the latch would never clear. */
    watchSprites() {
      const run = () => window.SLinkOverlay && window.SLinkOverlay.processSprites();
      let queued = false;
      new MutationObserver(() => {
        if (queued) return;
        queued = true;
        setTimeout(() => { queued = false; run(); }, 0);
      }).observe(document.body, { childList: true, subtree: true });
      run();
    },

    // ── theme / font / density ───────────────────────────────────────────
    applyTheme(slug) {
      this.theme = slug;
      document.getElementById('slink-theme').href = '/static/themes/' + slug + '.css';
      document.body.className = document.body.className
        .split(/\s+/).filter((c) => c && !c.startsWith('theme-')).concat('theme-' + slug).join(' ');
      localStorage.setItem('slink-theme', slug);
      this.syncDensity();
    },
    syncDensity() { document.body.classList.toggle('density-compact', this.compact); },
    applyFont(cls) {
      this.font = cls;
      document.body.classList.remove(...FONTS.map((f) => f[0]));
      document.body.classList.add(cls);
      localStorage.setItem('slink-mockup-font', cls);
    },

    // ── runs — the manager ───────────────────────────────────────────────
    run() { return this.runs.find((r) => r.run_id === this.activeRunId) || {}; },
    runsByStatus(s) { return this.runs.filter((r) => r.status === s); },
    isLive() { return this.run().status === 'running'; },

    /* What this run knows. A running run has the live payload. A stopped or archived one
     * has only what was persisted — the links — which is exactly what the Manager has for
     * it today (it reads links.json off disk). A run created in this session has nothing
     * yet, because no player has said hello. */
    status() {
      const r = this.run();
      if (!this.fixture) return EMPTY;
      if (r.created_in_mock) return EMPTY;
      if (r.status === 'running') return this.fixture;
      return { ...EMPTY, links: this.fixture.links, area_states: this.fixture.area_states,
               killfeed: this.fixture.killfeed, attempts_count: this.fixture.attempts_count,
               rules: this.fixture.rules,
               players: { a: { ...EMPTY.players.a, trainer_name: this.fixture.players.a.trainer_name, rom_type: this.fixture.players.a.rom_type },
                          b: { ...EMPTY.players.b, trainer_name: this.fixture.players.b.trainer_name, rom_type: this.fixture.players.b.rom_type } } };
    },

    selectRun(id) { this.activeRunId = id; this.dest = 'run'; this.tab = 'board'; this.launchersOpen = false; },

    newRun() {
      this.draft = { name: '', opts: { battle_calc: true, pc_trade_npc: true } };
      this.dest = 'new';
    },
    createRun() {
      const name = this.draft.name.trim();
      if (!name) return;
      const n = this.runs.length;
      const r = {
        run_id: 'run_' + Date.now(), name, status: 'stopped', created_in_mock: true,
        tcp_port: 54321 + n, http_port: 8081 + n,
        created_short: new Date().toISOString().slice(0, 16).replace('T', ' '),
        game_label: '', last_event: null, ...this.draft.opts,
      };
      this.runs.unshift(r);
      this.selectRun(r.run_id);
    },
    act(what) {
      const r = this.run();
      if (!r.run_id) return;
      if (what === 'start') r.status = 'running';
      if (what === 'stop') r.status = 'stopped';
      if (what === 'archive') { r.status = 'archived'; if (this.pinnedRunId === r.run_id) this.pinnedRunId = ''; }
      if (what === 'delete') {
        this.runs = this.runs.filter((x) => x.run_id !== r.run_id);
        if (this.pinnedRunId === r.run_id) this.pinnedRunId = '';
        this.activeRunId = (this.runs[0] || {}).run_id || '';
      }
      if (what === 'pin') this.pinnedRunId = this.pinnedRunId === r.run_id ? '' : r.run_id;
    },
    isPinned() { return this.pinnedRunId && this.pinnedRunId === this.run().run_id; },
    pinnedRun() { return this.runs.find((r) => r.run_id === this.pinnedRunId) || null; },

    // ── players ──────────────────────────────────────────────────────────
    player(pid) { return this.status().players[pid] || EMPTY.players[pid]; },
    /* Capabilities are per rom_type, not per generation: firered and firered_rr answer
     * differently on explode_mode and the native panel. */
    capsFor(pid) { return this.caps[this.player(pid).rom_type] || {}; },
    gameId(pid) { return this.capsFor(pid).game_id || ''; },
    /* No adapter predicate for held items (see brief §4): decide from the data. */
    anyHeldItems() {
      return ['a', 'b'].some((pid) =>
        Object.values(this.player(pid).party_details || {}).some((m) => m.held_item_id));
    },
    party(pid) {
      const p = this.player(pid);
      return (p.party_keys || []).map((k) => p.party_details[k] && { ...p.party_details[k], key: k }).filter(Boolean);
    },
    battle(pid) { return this.player(pid).battle_state || {}; },
    /* The mon the player has out, when they are in battle. Marked on its pair card, and
     * shown in the Now card beside the foe — that is the fight the partner's mon is in
     * too, whether or not the partner is looking. */
    activeMon(pid) {
      if (!this.battle(pid).in_battle) return null;
      return this.party(pid).find((x) => x.active) || null;
    },
    activeKey(pid) { const m = this.activeMon(pid); return m ? m.key : null; },
    wild(pid) { return Object.entries(this.player(pid).encounter_table || {}); },
    connected(pid) { return !!this.player(pid).connected; },
    /* Has this player ever said hello? Distinct from connected: a dropped client's last
     * state is kept by the server and shown until it reconnects, so the chip says
     * "disconnected" rather than pretending the player was never there. */
    hasData(pid) { return !!(this.player(pid).rom_type || this.party(pid).length); },
    anyData() { return this.hasData('a') || this.hasData('b'); },

    badgeCount(pid) { return ((this.player(pid).badges || 0).toString(2).match(/1/g) || []).length; },
    badgeSlots(pid) { return (this.capsFor(pid).badges || []).length || 8; },
    monsPerBox(pid) { return this.capsFor(pid).mons_per_box; },

    // ── the board ────────────────────────────────────────────────────────
    /* Where a mon is right now, with its live numbers if it is somewhere live. */
    locate(pid, key) {
      const p = this.player(pid);
      const inParty = (p.party_details || {})[key];
      if (inParty) return { ...inParty, key, where: 'party' };
      const inBox = (p.pc_boxes || []).find((b) => b.key === key);
      if (inBox) return { ...inBox, key, where: 'box' };
      return null;
    },

    /* One row per bond. Each half carries what the link recorded plus, if the run is live
     * and the mon is in a party, its current HP. */
    pairs() {
      const s = this.status();
      const kf = Object.fromEntries((s.killfeed || []).map((k) => [k.area_id, k]));
      return (s.links || []).map((l) => {
        const half = (pid) => {
          if (!l[pid + '_key']) return null;
          const live = this.locate(pid, l[pid + '_key']);
          return {
            key: l[pid + '_key'], nickname: l[pid + '_nickname'], species_name: l[pid + '_species_name'],
            level: (live && live.level) || l[pid + '_level'], sprite: l[pid + '_sprite_html'],
            shiny: l[pid + '_shiny'],
            hp: live && live.where === 'party' ? live.hp : null,
            maxHP: live && live.where === 'party' ? live.maxHP : null,
            where: live ? live.where : null,
            ability: live && live.ability_name, item: live && live.held_item_id,
            active: this.activeKey(pid) === l[pid + '_key'],
          };
        };
        const a = half('a'), b = half('b');
        const dead = l.status === 'dead' || l.status === 'memorial';
        const deadZone = !a && !b && (s.area_states || {})[l.area_id] === 'dead_zone';
        let section;
        if (dead || deadZone) section = 'fallen';
        else if (!a || !b) section = 'pending';
        else if (a.where === 'party' && b.where === 'party') section = 'party';
        else if (a.where === 'box' && b.where === 'box') section = 'boxed';
        else if (a.where && b.where) section = 'split';
        else section = 'linked';  // nothing is located: the run is not live
        const pcts = [a, b].filter((h) => h && h.hp != null).map((h) => Math.round((h.hp / Math.max(h.maxHP, 1)) * 100));
        const risk = pcts.length ? Math.min(...pcts) : null;
        return {
          area: l.area_id, areaName: l.area_display || this.areaName(l.area_id),
          status: deadZone ? 'dead_zone' : l.status, section, a, b, risk,
          atRisk: section === 'party' && risk != null && risk < RISK_PCT,
          death: kf[l.area_id] || null,
        };
      });
    },

    /* Captures waiting on the other player. One half filled, the other empty. */
    pendingRows() {
      const s = this.status();
      return Object.entries(s.pending_captures || {}).map(([area, sides]) => ({
        area, areaName: this.areaName(area), section: 'pending', status: 'pending',
        a: sides.a ? { ...sides.a, sprite: '', hp: null } : null,
        b: sides.b ? { ...sides.b, sprite: '', hp: null } : null,
        risk: null, atRisk: false, death: null,
      }));
    },

    /* Box mons that belong to no bond. Rare on a soul link — the quarantine rule deposits
     * an unlinked catch until it is linked — but they exist and the board should not
     * pretend otherwise. */
    unlinkedBoxed(pid) {
      const s = this.status();
      const spoken = new Set(s.links.flatMap((l) => [l.a_key, l.b_key]));
      // A pending catch sits in the box (quarantined until linked) but it is spoken for:
      // it already has a row under "waiting". Listing it here too showed it twice.
      for (const sides of Object.values(s.pending_captures || {})) {
        for (const m of Object.values(sides)) spoken.add(m.key);
      }
      return (this.player(pid).pc_boxes || []).filter((b) => !spoken.has(b.key));
    },

    sections() {
      const rows = [...this.pendingRows(), ...this.pairs()];
      // The team first; what is waiting on it second. Then the shelf, then the graveyard.
      const order = ['party', 'pending', 'split', 'boxed', 'linked', 'fallen'];
      return order.map((k) => [k, rows.filter((r) => r.section === k)]).filter(([, r]) => r.length);
    },

    counts() {
      const p = this.pairs();
      return { alive: p.filter((r) => r.section !== 'fallen').length, fallen: p.filter((r) => r.section === 'fallen').length };
    },

    // ── display helpers ──────────────────────────────────────────────────
    hpPct(m) { return m.hp == null ? 0 : Math.max(0, Math.min(100, Math.round((m.hp / Math.max(m.maxHP, 1)) * 100))); },
    hpClass(m) { const p = this.hpPct(m); return p > 50 ? '' : p > 20 ? 'mid' : 'low'; },
    areaName(id) { return (id || '').replace(/_/g, ' ').replace(/(\d+)/, ' $1').replace(/\s+/g, ' ').trim().replace(/\b\w/g, (c) => c.toUpperCase()); },
    shortTs(ts) { return (ts || '').slice(11, 19); },
    events(n) { return (this.status().recent_events || []).slice(0, n || 40); },
    deadZones() { return Object.entries(this.status().area_states || {}).filter(([, v]) => v === 'dead_zone').map(([k]) => k); },
    bondGlyph(status) { return status === 'alive' ? '<>' : status === 'pending' ? '<·' : '><'; },

    optionState(key) {
      const on = !!(this.status().rules || {})[key];
      const rule = OPTION_SUPPORT[key] || { all: true };
      let ok = true, why = '';
      for (const pid of ['a', 'b']) {
        const gid = this.gameId(pid);
        if (!gid) continue;                 // no cartridge yet: nothing is known to be impossible
        const rr = (this.player(pid).rom_type || '').endsWith('_rr');
        const specific = rule[gid + (rr ? '_rr' : '')] || rule[gid];
        const decided = specific ? specific.ok : rule.all;
        if (!decided) { ok = false; why = (specific && specific.why) || rule.why || ''; break; }
        if (specific && specific.why && !why) why = specific.why;
      }
      return { on, ok, why };
    },
  };
}

/* The shape a run has before any player has connected — or after the server for it has
 * stopped, for everything that is not persisted. Only the fields the templates touch. */
const EMPTY = {
  players: {
    a: { connected: false, rom_type: '', trainer_name: '', current_area_display: '', ball_count: 0, badges: 0,
         party_keys: [], party_details: {}, pc_boxes: [], battle_state: {}, encounter_table: {}, queued: 0 },
    b: { connected: false, rom_type: '', trainer_name: '', current_area_display: '', ball_count: 0, badges: 0,
         party_keys: [], party_details: {}, pc_boxes: [], battle_state: {}, encounter_table: {}, queued: 0 },
  },
  links: [], area_states: {}, pending_captures: {}, killfeed: [], recent_events: [],
  rules: {}, attempts_count: 0, save_failed: '',
};
