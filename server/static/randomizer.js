/* randomizer.js — the Alpine mixin behind _cartridges.html and _randomizer_fields.html.
 *
 * `randomizerFields(form)` returns the state and methods the fields need; a component
 * spreads it into its own object. `form` is window.SLINK_RANDOMIZER: the options the
 * pipeline supports (upr_settings.OPTIONS — the same table its allowlist is computed
 * from, in display order with kind/choices/range), the jar found on this machine, the
 * cartridges found in the SLink folder, the saved presets, which titles have a companion,
 * and what the run has already made. `rdraft` is what a run's cartridges are prepared
 * from: the two picks, the companion, Randomize and its `spec` (posted back as-is).
 *
 * `prepareCartridges(runId)` posts the draft to a run and resolves with the server's
 * answer. Every refusal names the setting or the file to fix, so the reason is surfaced
 * verbatim.
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
      // Start from what the run last made, so "prepare again" means the same unless
      // changed: the companion as before (on by default where one exists — the panel and
      // the native trade are what the companion is for), randomized as before.
      companion: form.cartridges ? !!form.cartridges.companion : true,
      randomize: !!(form.current),
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
    watchRandomizer() {
      var self = this;
      this.autoPick();
      this.preflight();
      ['rdraft.jar', 'rdraft.rom_a', 'rdraft.rom_b'].forEach(function (k) {
        self.$watch(k, function () { self.preflight(); });
      });
      // A different jar changes which pure ROMs are usable.
      this.$watch('rdraft.jar', function () { self.scanRoms(); });
    },
    async preflight() {
      var q = new URLSearchParams({ jar: this.rdraft.jar, rom_a: this.rdraft.rom_a, rom_b: this.rdraft.rom_b });
      try { this.pre = await (await fetch('/api/randomizer/status?' + q)).json(); } catch (_) { this.pre = null; }
    },
    async scanRoms() {
      try {
        var j = await (await fetch('/api/roms?' + new URLSearchParams({ jar: this.rdraft.jar }))).json();
        if (j.ok) { this.roms = j.roms; this.autoPick(); }
      } catch (_) { /* the list keeps what it had */ }
    },
    // A cartridge this run can take: clean, and of its family when it names one.
    usable(r) { return !!r.clean && (!this.family || r.family === this.family); },
    familyLabel(f) { return f === 'gen1_purergb' ? 'pureRGB' : f === 'gen1_rby' ? 'vanilla' : ''; },
    // The option's words: the cartridge, and why it is greyed when it is.
    romNote(r) {
      if (this.usable(r)) return r.title;
      if (r.clean && this.family) return r.title + ' (' + this.familyLabel(r.family) + '; this run is ' + this.familyLabel(this.family) + ')';
      return r.title || 'not a clean dump';
    },
    // The list, grouped: what this run can take first, then the other family, then the rest.
    romGroups() {
      var self = this, groups = [];
      function add(label, test) {
        var rs = self.roms.filter(test);
        if (rs.length) groups.push({ label: label, roms: rs });
      }
      if (this.family) {
        add(this.familyLabel(this.family) + ' — this run', function (r) { return self.usable(r); });
        add('other family', function (r) { return r.clean && !self.usable(r); });
      } else {
        add('pureRGB', function (r) { return r.clean && r.family === 'gen1_purergb'; });
        add('Red · Blue · Yellow', function (r) { return r.clean && r.family === 'gen1_rby'; });
      }
      add('not usable', function (r) { return !r.clean; });
      return groups;
    },
    // The creator's game chip changed: a pick of the wrong family goes, and the pair is
    // chosen again from what fits.
    setFamily(f) {
      var self = this;
      this.family = f || null;
      ['rom_a', 'rom_b'].forEach(function (k) {
        var r = self.roms.find(function (x) { return x.path === self.rdraft[k]; });
        if (r && !self.usable(r)) self.rdraft[k] = '';
      });
      this.autoPick();
    },
    // Two usable dumps in the folder and nothing chosen yet: that is the pair. Set after the
    // tick so the <option>s exist when x-model applies the value to the <select>.
    autoPick() {
      var self = this;
      this.$nextTick(function () {
        var ok = self.roms.filter(function (r) { return self.usable(r); });
        if (!ok.length || self.rdraft.rom_a || self.rdraft.rom_b) return;
        self.rdraft.rom_a = ok[0].path;
        self.rdraft.rom_b = (ok[1] || ok[0]).path;
      });
    },
    // The browser's own file dialog; the file lands in the SLink folder and is selected.
    async upload(ev, field) {
      var file = ev.target.files && ev.target.files[0];
      ev.target.value = '';
      if (!file) return;
      this.uploading = field; this.error = '';
      try {
        var body = new FormData(); body.append('file', file, file.name);
        var j = await (await fetch('/api/roms', { method: 'POST', body: body })).json();
        if (!j.ok) { this.error = j.error || 'Upload failed'; return; }
        if (j.kind === 'jar') { this.rdraft.jar = j.path; }
        else {
          if (!this.roms.some(function (r) { return r.path === j.path; })) this.roms.push(j.rom);
          this.rdraft[field] = j.path;
        }
      } catch (e) { this.error = String(e); }
      finally { this.uploading = ''; }
    },
    pick(pid) { var p = this.rdraft['rom_' + pid]; return this.roms.find(function (r) { return r.path === p; }) || null; },
    // The SLink companion exists for some titles only (rform.companion_titles): a pick
    // outside them greys the checkbox with the reason, as the run options do.
    companionOk() {
      var titles = this.rform.companion_titles || [];
      for (var i = 0; i < 2; i++) {
        var r = this.pick('ab'[i]);
        if (r && r.variant && titles.indexOf(r.variant) < 0) {
          return { ok: false, why: 'No companion build for ' + r.variant + ': it has no free WRAM for the mailbox. It plays fine with the Lua HUD.' };
        }
      }
      return { ok: true, why: '' };
    },
    // Can the run prepare cartridges from this draft? Nothing picked is fine (players
    // bring their own); one pick, an unusable pick, or randomizing without jar/java is not.
    cartsReady() { return !this.cartsWhy(); },
    cartsWhy() {
      var a = this.rdraft.rom_a, b = this.rdraft.rom_b;
      if (!a && !b) return this.rdraft.randomize ? 'Pick both cartridges to randomize.' : '';
      if (!a || !b) return 'Pick a cartridge for both players.';
      var ra = this.pick('a'), rb = this.pick('b');
      if ((ra && !this.usable(ra)) || (rb && !this.usable(rb))) return 'That cartridge cannot be used here.';
      if (this.pre && this.pre.roms && (this.pre.roms.a.clean === false || this.pre.roms.b.clean === false)) return 'A pick is not a pinned cartridge.';
      if (this.rdraft.randomize && this.pre && !this.pre.jar_found) return 'Randomizing needs PokeRandoZX.jar.';
      if (this.rdraft.randomize && this.pre && !this.pre.java_found) return 'Randomizing needs Java on PATH.';
      return '';
    },
    // identify()'s kind, in the table's words.
    kindWords(k) {
      return { clean: 'as picked', companion: 'with the SLink companion', rand: 'randomized',
               rand_companion: 'randomized, with the SLink companion' }[k] || k;
    },
    cartridgesBody() {
      var body = { rom_a: this.rdraft.rom_a, rom_b: this.rdraft.rom_b,
                   companion: !!this.rdraft.companion && this.companionOk().ok, randomize: !!this.rdraft.randomize };
      if (this.rdraft.randomize) { body.jar = this.rdraft.jar; body.spec = this.rdraft.spec; }
      return body;
    },
    async prepareCartridges(runId) {
      var res = await fetch('/api/runs/' + runId + '/cartridges', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.cartridgesBody()),
      });
      return await res.json();
    },
  };
}
