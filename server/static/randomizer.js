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
// Arrow / Home / End on a role="radiogroup" of chip buttons: move to the next enabled chip and
// select it (the chips carry a roving tabindex, so Tab enters the group at the checked one).
function radioKeys(e) {
  var step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1, Home: 'first', End: 'last' }[e.key];
  if (!step) return;
  var radios = Array.prototype.filter.call(e.currentTarget.querySelectorAll('[role="radio"]'), function (r) { return !r.disabled; });
  if (!radios.length) return;
  e.preventDefault();
  var i = radios.indexOf(document.activeElement);
  var next = step === 'first' ? radios[0] : step === 'last' ? radios[radios.length - 1]
    : radios[(Math.max(i, 0) + step + radios.length) % radios.length];
  next.focus();
  next.click();
}

function defaultSpec(form) {
  return Object.fromEntries(form.options.map(function (o) { return [o.key, o.default]; }));
}

function randomizerFields(form) {
  return {
    rform: form,
    pre: null,
    // Bumped on every preflight() call so a slow, stale response can recognize it is no
    // longer the latest and not overwrite `pre` out of order.
    _preSeq: 0,
    rdraft: {
      jar: form.jar || '', rom_a: '', rom_b: '',
      // Start from what the run last made, so "prepare again" means the same unless
      // changed. The companion is not a draft field: it goes in wherever one exists.
      randomize: !!(form.current),
      spec: Object.assign(defaultSpec(form), (form.current && form.current.spec) || {}),
    },
    roms: form.roms || [],
    // Named specs kept on this Manager (/api/presets); `preset` is the one the list shows,
    // `presetName` what Save writes.
    presets: form.presets || [],
    preset: '', presetName: '', presetNote: '',
    // Set while a same-named preset exists and Save is waiting for a second click to
    // confirm the overwrite (see savePreset) — cleared by editing the name.
    presetPendingOverwrite: null,
    // The family this run takes (upr_settings.FAMILY_*): fixed on a run's page, follows the
    // game chip in the creator (setFamily). null = any Gen 1 cartridge.
    family: form.family || null,
    uploading: '', uploadNote: '',
    groups() {
      var out = [], by = {};
      form.options.forEach(function (o) {
        if (!by[o.group]) { by[o.group] = { name: o.group, options: [] }; out.push(by[o.group]); }
        by[o.group].options.push(o);
      });
      return out;
    },
    resetSpec() { this.rdraft.spec = defaultSpec(form); },
    // The pure family's entries do not implement every option (option_form rows / choices
    // carry `pure: false`): on a pure pick those are greyed, and a value already set is
    // returned to its default so the pipeline's named refusal never comes from the form.
    PURE_WHY: 'not available for pureRGB',
    // What admission refuses under another choice (both families; upr_settings
    // GLOBAL_UNVERIFIABLE_RESTRICTIONS / forbidden_enabled), greyed while that choice
    // holds. `off` names a choice option's values; no `off` greys the whole option.
    //  - under a global 1-to-1 wild map only restriction "none" stands: game1to1Encounters
    //    ignores type_themed / catch_em_all, and similar-strength is not verifiable there
    //    (the global picker's pool shrinks across the whole map);
    //  - evenly distributed trainers + similar strength: the placement-history filter
    //    precedes the strength band, so the band is not verifiable.
    DEPENDS: {
      wild_restriction: { on: 'wild', when: 'global', off: ['type_themed', 'catch_em_all', 'similar'],
                          why: 'not available under a global 1-to-1 map' },
      trainers_similar_strength: { on: 'trainers', when: 'distributed',
                                   why: 'not available with evenly distributed trainer teams' },
    },
    // A row another family owns (option_form `families`: the FR/LG-only held items, tutors,
    // trades, shops, pickup and tweaks; the Gen 1-only tweaks) is greyed like a pure one.
    optWhy(o) {
      if (this.family && o.families && o.families.indexOf(this.family) < 0) return 'not available for ' + this.familyLabel(this.family);
      if (!this.family && o.families && o.families.indexOf('gen1_rby') < 0) return 'Gen 3 only';
      if (this.family === 'gen1_purergb' && o.pure === false) return this.PURE_WHY;
      var d = this.DEPENDS[o.key];
      if (d && !d.off && this.rdraft.spec[d.on] === d.when) return d.why;
      return '';
    },
    optOk(o) { return !this.optWhy(o); },
    choiceWhy(o, c) {
      if (this.family === 'gen1_purergb' && c.pure === false) return this.PURE_WHY;
      var d = this.DEPENDS[o.key];
      if (d && d.off && this.rdraft.spec[d.on] === d.when && d.off.indexOf(c.value) >= 0) return d.why;
      return '';
    },
    choiceOk(o, c) { return !this.choiceWhy(o, c); },
    // Roving tabindex for a choice's radio chips: the checked chip if it is enabled, else the
    // first enabled one, is the group's single Tab stop (radioKeys moves within it).
    chipTab(o, c) {
      var self = this, on = o.choices.filter(function (x) { return self.choiceOk(o, x); });
      var stop = on.find(function (x) { return x.value === self.rdraft.spec[o.key]; }) || on[0];
      return stop === c ? 0 : -1;
    },
    // The preflight in words: the tags and the status region say the same thing.
    jarWords() {
      var p = this.pre;
      if (!p) return '';
      if (!p.jar_found) return 'jar not found';
      if (p.jar_fork) return 'SLink fork jar (vanilla + pureRGB + FireRed / LeafGreen + Emerald)';
      return this.family === 'gen3_frlg' || this.family === 'gen3_emerald'
        ? 'stock jar (not accepted for ' + this.familyLabel(this.family) + ')' : 'stock jar (vanilla only)';
    },
    javaWords() { return !this.pre ? '' : this.pre.java_found ? 'java on PATH' : 'java not on PATH'; },
    setChoice(o, c) { this.rdraft.spec[o.key] = c.value; this.settleSpecForFamily(); },
    // what the chosen chip means, written out under the row (the tooltip needs a hover)
    chosenHelp(o) {
      var c = o.choices.find(function (x) { return x.value === this.rdraft.spec[o.key]; }, this);
      return (c && c.help) || '';
    },
    // A value that is not allowed any more -- by the family or by another choice -- goes
    // back to its default, so the refusal never comes from the form.
    settleSpecForFamily() {
      var self = this;
      form.options.forEach(function (o) {
        if (!self.optOk(o)) { self.rdraft.spec[o.key] = o.default; return; }
        if (o.kind === 'choice') {
          var cur = o.choices.find(function (c) { return c.value === self.rdraft.spec[o.key]; });
          if (cur && !self.choiceOk(o, cur)) self.rdraft.spec[o.key] = o.default;
        }
      });
    },
    // ── presets: the spec by name, on this Manager or as a file ────────────────────────
    // Only known options land, over the defaults, so an older or hand-edited preset
    // still loads; the server checks the same thing before it saves.
    applySpec(spec) {
      var known = defaultSpec(form);
      Object.keys(spec || {}).forEach(function (k) { if (k in known) known[k] = spec[k]; });
      this.rdraft.spec = known;
      this.settleSpecForFamily();
    },
    loadPreset(name) {
      var p = this.presets.find(function (x) { return x.name === name; });
      if (!p) return;
      this.applySpec(p.spec); this.presetName = p.name; this.presetNote = 'Loaded "' + p.name + '"';
    },
    async savePreset() {
      var name = this.presetName.trim();
      if (!name) { this.presetNote = 'Give the preset a name.'; return; }
      var existing = this.presets.find(function (x) { return x.name.toLowerCase() === name.toLowerCase(); });
      // the pending flag alone decides: the server may know a same-named preset this page doesn't
      var overwrite = this.presetPendingOverwrite === name.toLowerCase();
      // A same-named preset exists and this isn't the confirming click yet: ask inline
      // (window.confirm doesn't work in every context this page can run in) rather than
      // silently replacing it. Clicking Save again with the same name confirms; editing
      // the name (see the presetName $watch in watchRandomizer) cancels.
      if (existing && !overwrite) {
        this.presetPendingOverwrite = name.toLowerCase();
        this.presetNote = 'A preset named "' + existing.name + '" already exists. '
          + 'Replace: click Save again. Cancel: change the name.';
        return;
      }
      this.presetPendingOverwrite = null;
      try {
        var res = await fetch('/api/presets', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                               body: JSON.stringify({ name: name, spec: this.rdraft.spec, overwrite: overwrite }) });
        var j = null;
        try { j = await res.json(); } catch (_) { /* not JSON */ }
        if (res.status === 409 && !overwrite) {
          this.presetPendingOverwrite = name.toLowerCase();
          this.presetNote = 'A preset named "' + name + '" already exists. Replace: click Save again. Cancel: change the name.';
          return;
        }
        if (!res.ok || !j || !j.ok) { this.presetNote = (j && j.error) || ('Save failed (' + res.status + ')'); return; }
        this.presets = this.presets.filter(function (x) { return x.name.toLowerCase() !== name.toLowerCase(); }).concat([j.preset])
          .sort(function (a, b) { return a.name.toLowerCase() < b.name.toLowerCase() ? -1 : 1; });
        this.preset = j.preset.name; this.presetNote = 'Saved "' + j.preset.name + '"';
      } catch (e) { this.presetNote = 'Save failed: ' + e.message; }
    },
    async deletePreset() {
      var name = this.preset;
      if (!name || !confirm('Delete preset "' + name + '"?')) return;
      try {
        var res = await fetch('/api/presets/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                        body: JSON.stringify({ name: name }) });
        var j = null;
        try { j = await res.json(); } catch (_) { /* not JSON */ }
        if (!res.ok || !j || !j.ok) { this.presetNote = (j && j.error) || ('Delete failed (' + res.status + ')'); return; }
        this.presets = this.presets.filter(function (x) { return x.name !== name; });
        this.preset = ''; this.presetNote = 'Deleted "' + name + '"';
      } catch (e) { this.presetNote = 'Delete failed: ' + e.message; }
    },
    // The file that leaves this machine is UPR's own: a .rnqs, which UPR's GUI opens and
    // which is what a run keeps. Export builds it from the form; import admits one through
    // the pipeline's gates and reads it back -- a refusal names what the file changes.
    async exportSettings() {
      var name = this.presetName.trim() || 'slink';
      var res = await fetch('/api/randomizer/settings/export', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                                 body: JSON.stringify({ spec: this.rdraft.spec, name: name, family: this.family }) });
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
        // Which allowlist admits the file: pureRGB's is stricter. null (no run yet, or a
        // run not tied to a family) sends nothing and the server defaults to vanilla.
        if (this.family) body.append('family', this.family);
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
      // Editing the name cancels a pending overwrite confirmation (see savePreset).
      this.$watch('presetName', function () { self.presetPendingOverwrite = null; });
    },
    async preflight() {
      // watchRandomizer fires this on every jar/rom_a/rom_b change with no ordering: a
      // slow response to an earlier pick could otherwise land after, and overwrite, a
      // newer one's answer.
      var seq = ++this._preSeq;
      var q = new URLSearchParams({ jar: this.rdraft.jar, rom_a: this.rdraft.rom_a, rom_b: this.rdraft.rom_b });
      var result = null;
      try {
        var res = await fetch('/api/randomizer/status?' + q);
        if (res.ok) result = await res.json();
      } catch (_) { result = null; }
      if (seq !== this._preSeq) return;   // superseded by a later call; drop this answer
      this.pre = result;
    },
    async scanRoms() {
      try {
        var j = await (await fetch('/api/roms?' + new URLSearchParams({ jar: this.rdraft.jar }))).json();
        if (j.ok) { this.roms = j.roms; this.autoPick(); }
      } catch (_) { /* the list keeps what it had */ }
    },
    // A cartridge this run can take: clean, and of its family when it names one.
    usable(r) { return !!r.clean && (!this.family || r.family === this.family); },
    familyLabel(f) { return f === 'gen1_purergb' ? 'pureRGB' : f === 'gen1_rby' ? 'vanilla' : f === 'gen2_gsc' ? 'Gen 2' : f === 'gen3_frlg' ? 'FireRed / LeafGreen' : f === 'gen3_emerald' ? 'Emerald' : ''; },
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
        add('FireRed · LeafGreen', function (r) { return r.clean && r.family === 'gen3_frlg'; });
        add('Emerald', function (r) { return r.clean && r.family === 'gen3_emerald'; });
        add('Gold · Silver · Crystal', function (r) { return r.clean && r.family === 'gen2_gsc'; });
      }
      add('not usable', function (r) { return !r.clean; });
      return groups;
    },
    // The creator's game chip changed: a pick of the wrong family goes, and the pair is
    // chosen again from what fits.
    setFamily(f) {
      var self = this;
      this.family = f || null;
      this.settleSpecForFamily();
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
        // Only a SECOND distinct cartridge fills B; one usable ROM must not hand both
        // players the same file.
        if (ok.length > 1) self.rdraft.rom_b = ok[1].path;
      });
    },
    // The browser's own file dialog; the file lands in the SLink folder and is selected.
    async upload(ev, field) {
      var file = ev.target.files && ev.target.files[0];
      ev.target.value = '';
      if (!file) return;
      this.uploading = field; this.error = ''; this.uploadNote = '';
      try {
        var body = new FormData(); body.append('file', file, file.name);
        var j = await (await fetch('/api/roms', { method: 'POST', body: body })).json();
        if (!j.ok) { this.error = j.error || 'Upload failed'; return; }
        this.uploadNote = j.existing ? file.name + ' is already here as ' + j.rom.name + '; picked that.'
                                     : 'Added ' + file.name + '.';
        if (j.kind === 'jar') { this.rdraft.jar = j.path; }
        else {
          if (!this.roms.some(function (r) { return r.path === j.path; })) this.roms.push(j.rom);
          this.rdraft[field] = j.path;
        }
      } catch (e) { this.error = String(e); }
      finally { this.uploading = ''; }
    },
    pick(pid) { var p = this.rdraft['rom_' + pid]; return this.roms.find(function (r) { return r.path === p; }) || null; },
    // The SLink companion exists for some titles only (rform.companion_titles): it is
    // patched into every pick that has one; a pick outside them is handed out as picked.
    companionOk() {
      var titles = this.rform.companion_titles || [];
      for (var i = 0; i < 2; i++) {
        var r = this.pick('ab'[i]);
        if (r && r.variant && titles.indexOf(r.variant) < 0) {
          if (r.family === 'gen3_emerald') return { ok: false, why: 'No Emerald companion build is available yet. Use the standard cartridge.' };
          return { ok: false, why: 'No companion build for ' + r.variant + ': it has no free WRAM for the mailbox. The cartridge is handed out as picked: the Soul Link rules are the same, without the panel, native trade or native sounds.' };
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
      if (this.rdraft.randomize && this.family === 'gen2_gsc') return 'Gen 2 has no randomizer support; turn Randomize off.';
      if (this.rdraft.randomize && this.pre && !this.pre.jar_found) return 'Randomizing needs PokeRandoZX.jar.';
      if (this.rdraft.randomize && this.pre && this.pre.jar_found && this.pre.jar_trusted === false) {
        return this.pre.jar_error || 'This PokeRandoZX.jar is not a known build; SLink will not run it.';
      }
      if (this.rdraft.randomize && this.pre && !this.pre.java_found) return 'Randomizing needs Java on PATH.';
      // pinned is pinned whatever the jar; the FORK is the randomizer's requirement for pure
      if (this.rdraft.randomize && this.family === 'gen1_purergb' && this.pre && this.pre.jar_found && !this.pre.jar_fork) {
        return 'Randomizing pureRGB needs the current SLink fork jar (tools/build_upr_fork.py); this jar is the stock 4.6.1 or an older fork.';
      }
      if (this.rdraft.randomize && (this.family === 'gen3_frlg' || this.family === 'gen3_emerald')
          && this.pre && this.pre.jar_found && !this.pre.jar_fork) {
        return 'Randomizing ' + this.familyLabel(this.family) + ' needs the current SLink fork jar.';
      }
      if (this.rdraft.randomize && this.family === 'gen1_purergb'
          && this.pre && this.pre.jar_entries) {
        // pure + companion + randomize is the overlay path: UPR needs an entry for the
        // overlay build of each pick ("PureRed overlay (U)"; the fork's naming).
        var entries = this.pre.jar_entries, missing = [];
        var titles = this.rform.companion_titles || [];
        [ra, rb].forEach(function (r) { if (r && r.variant && titles.indexOf(r.variant) >= 0 && entries.indexOf(r.variant + ' overlay (U)') < 0) missing.push(r.variant); });
        if (missing.length) return 'This jar has no entry for the companion overlay of ' + missing.join(' / ') + ': rebuild the SLink fork, or turn Randomize off.';
      }
      return '';
    },
    // identify()'s kind, in the table's words.
    kindWords(k) {
      return { clean: 'as picked', companion: 'with the SLink companion', rand: 'randomized',
               rand_companion: 'randomized, with the SLink companion' }[k] || k;
    },
    cartridgesBody() {
      var body = { rom_a: this.rdraft.rom_a, rom_b: this.rdraft.rom_b,
                   // patch-first: the server decides per player (server/cartridges.py); a pick
                   // without an admitted companion goes out as picked, its partner still patched
                   companion: true, randomize: !!this.rdraft.randomize };
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
