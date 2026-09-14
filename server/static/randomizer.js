/* randomizer.js — the Alpine mixin behind _randomizer_fields.html.
 *
 * `randomizerFields(form)` returns the state and methods the fields need; a component
 * spreads it into its own object. `form` is window.SLINK_RANDOMIZER: the options the
 * pipeline supports (upr_settings.OPTIONS — the same table its allowlist is computed
 * from, in display order with kind/choices/range), the jar found on this machine, and the
 * run's current pair when there is one. `rdraft.spec` is posted back as-is.
 *
 * `randomizePair(runId)` posts the draft to a run and resolves with the server's answer.
 * Every refusal names the setting or the file to fix, so the reason is surfaced verbatim.
 */
function defaultSpec(form) {
  return Object.fromEntries(form.options.map(function (o) { return [o.key, o.default]; }));
}

function randomizerFields(form) {
  return {
    rform: form,
    pre: null,
    rdraft: {
      jar: form.jar || '', rom_a: '', rom_b: '',
      // Start from the run's last pair when there is one, so "build again" means the
      // same settings unless changed.
      spec: Object.assign(defaultSpec(form), (form.current && form.current.spec) || {}),
    },
    picker: { field: '', ext: '', dir: '', parent: null, entries: [] },
    groups() {
      var out = [], by = {};
      form.options.forEach(function (o) {
        if (!by[o.group]) { by[o.group] = { name: o.group, options: [] }; out.push(by[o.group]); }
        by[o.group].options.push(o);
      });
      return out;
    },
    resetSpec() { this.rdraft.spec = defaultSpec(form); },
    watchRandomizer() {
      var self = this;
      this.preflight();
      ['rdraft.jar', 'rdraft.rom_a', 'rdraft.rom_b'].forEach(function (k) {
        self.$watch(k, function () { self.preflight(); });
      });
    },
    async preflight() {
      var q = new URLSearchParams({ jar: this.rdraft.jar, rom_a: this.rdraft.rom_a, rom_b: this.rdraft.rom_b });
      try { this.pre = await (await fetch('/api/randomizer/status?' + q)).json(); } catch (_) { this.pre = null; }
    },
    async browse(field, ext) {
      this.picker.field = field; this.picker.ext = ext;
      var cur = this.rdraft[field] || '';
      var i = Math.max(cur.lastIndexOf('/'), cur.lastIndexOf('\\'));
      await this.list(i > 0 ? cur.slice(0, i) : '');
    },
    async list(dir) {
      var q = new URLSearchParams({ dir: dir || '', ext: this.picker.ext || '' });
      var j = await (await fetch('/api/browse?' + q)).json();
      if (!j.ok) { this.error = j.error; return; }
      this.picker.dir = j.dir; this.picker.parent = j.parent; this.picker.entries = j.entries;
    },
    pick(path) { this.rdraft[this.picker.field] = path; this.picker.field = ''; },
    randomizeBody() {
      return { jar: this.rdraft.jar, rom_a: this.rdraft.rom_a, rom_b: this.rdraft.rom_b, spec: this.rdraft.spec };
    },
    async randomizePair(runId) {
      var res = await fetch('/api/runs/' + runId + '/randomize', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.randomizeBody()),
      });
      return await res.json();
    },
  };
}
