<script>
  import { app, bothPlayers, currentRun } from '../lib/store.svelte.js';
  import { RUN_OPTIONS } from '../lib/caps.js';

  const players = $derived(bothPlayers());
  const run = $derived(currentRun());
  const rules = $derived(app.status?.rules || {});

  // A rule's availability is decided per CARTRIDGE, so an option can be live for
  // one player and impossible for the other. Returns true / false / null(unknown).
  function availability(opt, c) {
    if (!opt.gate) return true;
    return c[opt.gate === 'explode_mode' ? 'explode' : 'infoPanel'];
  }
</script>

<div class="pane">
  <section class="card">
    <h3>Rules</h3>
    <p class="card-sub">
      Availability is a property of each player's cartridge, not of the run — so it is
      shown once per player. An option neither cartridge can run is marked unavailable
      in place, never offered as a checkbox that does nothing (brief §4).
    </p>
    {#each RUN_OPTIONS as opt (opt.key)}
      {@const av = players.map((c) => availability(opt, c))}
      {@const none = av.every((x) => x === false)}
      <div class="optrow" class:unavailable={none}>
        <span>{opt.label}</span>
        {#each players as c, i (c.side)}
          <span class="why">
            {c.side.toUpperCase()} · {c.label}:
            {#if av[i] === true}<span class="on">available</span>
            {:else if av[i] === false}<span class="na">unavailable</span>
            {:else}<span class="unk">unknown</span>{/if}
          </span>
        {/each}
        <span class="state">
          {#if none}
            <span class="na">not offered</span>
          {:else}
            <span class={rules[opt.key] ?? run?.[opt.key] ? 'on' : 'off'}>
              {rules[opt.key] ?? run?.[opt.key] ? 'on' : 'off'}
            </span>
          {/if}
        </span>
      </div>
    {/each}
  </section>

  <div class="cols">
    {#each players as c (c.side)}
      <section class="card">
        <h3>Cartridge {c.side.toUpperCase()} · {c.p?.trainer_name}</h3>
        <dl class="kv">
          <dt>Game</dt><dd>{c.label}</dd>
          <dt>rom_type</dt><dd><code>{c.romType || '—'}</code></dd>
          <dt>Capability row</dt>
          <dd>
            {#if c.capsFound}
              <code>{c.capsKey}</code>
              {#if c.capsInferred}<span class="unk">inferred — same family, no own row</span>{/if}
            {:else}
              <span class="unk">no row for “{c.romType}”</span>
            {/if}
          </dd>
          <dt>Adapter</dt><dd><code>{c.caps.game_id || '—'}</code></dd>
          <dt>Party blob</dt>
          <dd>{#if c.partyBlob}{c.partyBlob} bytes/mon{:else}<span class="unk">unknown</span>{/if}</dd>
          <dt>Seed</dt><dd><span class="unk">not in the status payload</span></dd>
          <dt>ROM SHA1</dt><dd><span class="unk">not in the status payload</span></dd>
          <dt>Identity</dt>
          <dd>{c.p?.identity_error ? c.p.identity_error : 'ok'}</dd>
        </dl>

        <h3 style="margin-top:1em">Encounter table</h3>
        <!-- Per player. Randomized pairs mean these differ between the two
             cartridges, so there is deliberately no shared table here (brief §5). -->
        {#if c.p?.encounter_table == null}
          <p class="absent-note">
            <span class="unk">unknown</span> — <code>players.{c.side}.encounter_table</code>
            is null in this fixture. Not the same as "no encounters": the client has not
            reported one for {c.p?.current_area_display || 'this area'} yet.
          </p>
        {:else}
          <p class="card-sub">{c.p.current_area_display} · as reported by {c.p?.trainer_name}'s client</p>
          <div class="scroll-x">
            <table class="grid">
              <thead><tr><th>Method</th><th>Species</th><th>Lv</th><th>Rate</th></tr></thead>
              <tbody>
                {#each Object.entries(c.p.encounter_table) as [method, rows] (method)}
                  {#each rows as e, i (method + i)}
                    <tr>
                      <td class="dim">{i === 0 ? method : ''}</td>
                      <td>{e.name}</td>
                      <td>{e.min_level}{e.max_level !== e.min_level ? `–${e.max_level}` : ''}</td>
                      <td>{e.rate}%</td>
                    </tr>
                  {/each}
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </section>
    {/each}
  </div>

  <section class="card">
    <h3>Randomizer</h3>
    <p class="card-sub">
      A first-class setup step, not a collapsed disclosure: the seeds recorded here are
      the only record of what each player is playing — UPR's CLI has no seed flag and
      writes it only to its log (brief §5).
    </p>
    <div class="optrow"><span>1 · Randomizer jar</span><span class="state"><span class="unk">not selected</span></span></div>
    <div class="optrow"><span>2 · Settings file (shared by both players)</span><span class="state"><span class="unk">not selected</span></span></div>
    {#each players as c (c.side)}
      <div class="optrow">
        <span>3{c.side} · Clean ROM for {c.p?.trainer_name} ({c.label})</span>
        <span class="state"><span class="unk">not selected</span></span>
      </div>
    {/each}
    <div class="optrow">
      <span>4 · Roll both seeds and record SHA1s</span>
      <span class="state"><button class="btn" disabled>Run</button></span>
    </div>
  </section>
</div>
