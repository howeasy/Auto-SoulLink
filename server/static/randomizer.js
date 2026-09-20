/* randomizer.js — the Alpine mixin behind _randomizer_fields.html.
 *
 * `randomizerFields(form)` returns the state and methods the fields need; a component
 * spreads it into its own object. `form` is window.SLINK_RANDOMIZER: the options the
 * pipeline supports (upr_settings.OPTIONS — the same table its allowlist is computed
 * from, in display order with kind/choices/range), the jar found on this machine, the ROMs
 * found in the SLink folder, and the run's current pair when there is one. `rdraft.spec`
 * is posted back as-is.
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
    // Why a cartridge is greyed, in the option's own words.
    romNote(r) {
      if (this.usable(r)) return r.title;
      if (r.clean && this.family) return r.title + ' — ' + this.familyLabel(r.family) + ', this run is ' + this.familyLabel(this.family);
      return r.title || 'not a clean dump';
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
