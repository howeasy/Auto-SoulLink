<script>
  import { app, bothPlayers } from './lib/store.svelte.js';

  let { run } = $props();
  const players = $derived(bothPlayers());
  const st = $derived(app.status);
</script>

<header class="run-hdr">
  <div class="run-hdr-top">
    <h2 class="run-name">{run?.name || '—'}</h2>
    <span class="pill {run?.status || 'stopped'}">{run?.status || 'unknown'}</span>
    {#if st?.run_over}<span class="pill dead">run over</span>{/if}
    <span class="dim" style="font-size:.76em">attempt {st?.attempts_count ?? '—'}</span>
    <div class="hdr-actions">
      {#if run?.status === 'running'}
        <button class="btn">Stop</button>
        <button class="btn">Pin</button>
      {:else}
        <button class="btn">Start</button>
      {/if}
    </div>
  </div>

  <!-- Per-player chips. Game label lives HERE, not on the run: the two players can
       hold different versions of the same generation (brief §5). -->
  <div class="player-strip">
    {#each players as c (c.side)}
      <div class="pchip">
        <span class="side">{c.side.toUpperCase()}</span>
        <span class="who">{c.p?.trainer_name || '—'}</span>
        <span class="game">{c.label}</span>
        <span class="dot {c.p?.connected ? 'running' : 'stopped'}"
              title={c.p?.connected ? 'connected' : `last seen ${c.p?.last_seen || '—'}`}></span>
        <span class="dim" style="font-size:.85em">{c.p?.badges ?? 0}◆ · {c.p?.ball_count ?? 0} balls</span>
        <span class="area">{c.p?.current_area_display || '—'}</span>
      </div>
    {/each}
  </div>
</header>
