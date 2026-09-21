/* randomizer.js — the Alpine mixin behind _randomizer_fields.html.
 *
 * `randomizerFields(form)` returns the state and methods the fields need; a component
 * spreads it into its own object. `form` is window.SLINK_RANDOMIZER: the options the
 * pipeline supports (upr_settings.OPTIONS — the same table its allowlist is computed
 * from, in display order with kind/choices/range), the jar found on this machine, the ROMs
 * found in the SLink folder, the saved presets, and the run's current pair when there is
 * one. `rdraft.spec` is posted back as-is.
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
    roms: form.roms || [],
    // Named specs kept on this Manager (/api/presets); `preset` is the one the list shows,
    // `presetName` what Save writes.
    presets: form.presets || [],
    preset: '', presetName: '', presetNote: '',
    // The family this run takes (upr_settings.FAMILY_*): fixed on a run's page, follows the
    // game chip in the creator (setFamily). null = any Gen 1 cartridge.
    family: form.family || null,
    uploading: '',
    groups() {
      var out = [], by = {};
      form.options.forEach(function (o) {
        if (!by[o.group]) { by[o.group] = { name: o.group, options: [] }; out.push(by[o.group]); }
        by[o.group].options.push(o);
      });
      return out;
    },
    resetSpec() { this.rdraft.spec = defaultSpec(form); },
    // ── presets: the spec by name, on this Manager or as a file ────────────────────────
    // Only known options land, over the defaults, so an older or hand-edited preset
    // still loads; the server checks the same thing before it saves.
    applySpec(spec) {
      var known = defaultSpec(form);
      Object.keys(spec || {}).forEach(function (k) { if (k in known) known[k] = spec[k]; });
      this.rdraft.spec = known;
    },
    loadPreset(name) {
      var p = this.presets.find(function (x) { return x.name === name; });
      if (!p) return;
      this.applySpec(p.spec); this.presetName = p.name; this.presetNote = 'Loaded "' + p.name + '"';
    },
    async savePreset() {
      var name = this.presetName.trim();
      if (!name) { this.presetNote = 'Give the preset a name.'; return; }
      var res = await fetch('/api/presets', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                             body: JSON.stringify({ name: name, spec: this.rdraft.spec }) });
      var j = await res.json();
      if (!j.ok) { this.presetNote = j.error || 'Save failed'; return; }
      this.presets = this.presets.filter(function (x) { return x.name.toLowerCase() !== name.toLowerCase(); }).concat([j.preset])
        .sort(function (a, b) { return a.name.toLowerCase() < b.name.toLowerCase() ? -1 : 1; });
      this.preset = j.preset.name; this.presetNote = 'Saved "' + j.preset.name + '"';
    },
    async deletePreset() {
      var name = this.preset;
      if (!name || !confirm('Delete preset "' + name + '"?')) return;
      var j = await (await fetch('/api/presets/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                          body: JSON.stringify({ name: name }) })).json();
      if (!j.ok) { this.presetNote = j.error || 'Delete failed'; return; }
      this.presets = this.presets.filter(function (x) { return x.name !== name; });
      this.preset = ''; this.presetNote = 'Deleted "' + name + '"';
    },
    // The file that leaves this machine is UPR's own: a .rnqs, which UPR's GUI opens and
    // which is what a run keeps. Export builds it from the form; import admits one through
    // the pipeline's gates and reads it back -- a refusal names what the file changes.
    async exportSettings() {
      var name = this.presetName.trim() || 'slink';
      var res = await fetch('/api/randomizer/settings/export', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                                 body: JSON.stringify({ spec: this.rdraft.spec, name: name }) });
      if (!res.ok) { var j = await res.json(); this.presetNote = j.error || 'Export failed'; return; }
      var a = document.createElement('a');
      a.href = URL.createObjectURL(await res.blob()); a.download = name.replace(/[^\w-]+/g, '_') + '.rnqs';
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
      this.presetNote = "Exported " + a.download + " — UPR's own settings file; it opens in the randomizer's GUI too.";
    },
    async importSettings(ev) {
      var file = ev.target.files && ev.target.files[0];
      ev.target.value = '';
      if (!file) return;
      try {
        var body = new FormData(); body.append('file', file, file.name);
        var j = await (await fetch('/api/randomizer/settings/import', { method: 'POST', body: body })).json();
        if (!j.ok) { this.presetNote = file.name + ': ' + (j.error || 'not admitted'); return; }
        this.applySpec(j.spec);
        this.presetName = file.name.replace(/\.rnqs$/i, '');
        this.presetNote = 'Loaded ' + file.name + ' — ' + j.summary + '. Save keeps it on this Manager.';
      } catch (e) { this.presetNote = 'Import failed: ' + e.message; }
    },
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
