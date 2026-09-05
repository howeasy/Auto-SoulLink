<script>
  import { app, loadGen, applyTheme, applyFont, applyDensity, THEMES } from './lib/store.svelte.js';

  const GROUPS = ['running', 'stopped', 'archived'];
  const grouped = $derived(GROUPS.map((s) => [s, app.runs.filter((r) => r.status === s)]));
</script>

<nav class="rail">
  <h1 class="brand">SOUL<br />LINK</h1>

  <!-- Gen toggle: swaps the whole status payload, so every capability-driven
       panel below re-evaluates. Brief §8.2. -->
  <div>
    <p class="rail-head">Fixture</p>
    <div class="seg">
      <button class:active={app.gen === 'gen3'} onclick={() => loadGen('gen3')}>Gen 3</button>
      <button class:active={app.gen === 'gen1'} onclick={() => loadGen('gen1')}>Gen 1</button>
    </div>
  </div>

  <div>
    <p class="rail-head">Runs</p>
    {#each grouped as [status, runs] (status)}
      {#if runs.length}
        <div class="rail-group">
          {#each runs as r (r.run_id)}
            <button class="run-btn" class:active={app.runId === r.run_id}
                    onclick={() => (app.runId = r.run_id)}>
              <span class="dot {r.status}"></span>
              <span class="nm">{r.name}</span>
            </button>
          {/each}
        </div>
      {/if}
    {/each}
  </div>

  <hr class="rail-sep" />

  <div class="rail-group">
    <button class="dest" aria-current="true">Run</button>
    <button class="dest" disabled>Broadcast <span class="stub">L1 stub</span></button>
    <button class="dest" disabled>Tools <span class="stub">L1 stub</span></button>
  </div>

  <div class="rail-foot">
    <div>
      <p class="rail-head">Font</p>
      <div class="seg">
        <button class:active={!app.fontClassic} onclick={() => applyFont(false)}>Pixel</button>
        <button class:active={app.fontClassic} onclick={() => applyFont(true)}>Classic</button>
      </div>
    </div>
    <div>
      <p class="rail-head">Density</p>
      <div class="seg">
        <button class:active={app.density === 'comfortable'} onclick={() => applyDensity('comfortable')}>Comfy</button>
        <button class:active={app.density === 'compact'} onclick={() => applyDensity('compact')}>Compact</button>
      </div>
    </div>
    <div>
      <p class="rail-head">Theme</p>
      <div class="swatches">
        {#each THEMES as [slug, label, swatch] (slug)}
          <button class="swatch" class:active={app.theme === slug}
                  style="background:{swatch}" title={label} aria-label={label}
                  onclick={() => applyTheme(slug)}></button>
        {/each}
      </div>
    </div>
  </div>
</nav>
