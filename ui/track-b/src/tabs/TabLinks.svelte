<script>
  import { app, bothPlayers } from '../lib/store.svelte.js';
  import MonCell from '../MonCell.svelte';
  import { areaLabel } from '../lib/fmt.js';

  const st = $derived(app.status);
  const players = $derived(bothPlayers());
  const links = $derived(st?.links || []);
  const areas = $derived(Object.entries(st?.area_states || {}));

  const half = (l, s) => ({
    key: l[`${s}_key`], nickname: l[`${s}_nickname`],
    species_name: l[`${s}_species_name`], species_id: l[`${s}_species`],
    level: l[`${s}_level`], shiny: l[`${s}_shiny`],
    sprite_html: l[`${s}_sprite_html`],
  });
</script>

<div class="pane">
  <section class="card">
    <h3>Soul links · {links.length}</h3>
    <div class="scroll-x">
      <table class="grid">
        <thead>
          <tr>
            <th>Area</th>
            <th>{players[0].p?.trainer_name || 'A'} · {players[0].label}</th>
            <th>{players[1].p?.trainer_name || 'B'} · {players[1].label}</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {#each links as l (l.a_key + l.b_key)}
            <tr>
              <td class="lk-area">{l.area_display || areaLabel(l.area_id)}</td>
              {#each ['a', 'b'] as s (s)}
                <td>
                  {#if l[`${s}_species`]}
                    <span style="display:flex;align-items:center;gap:8px">
                      <MonCell mon={half(l, s)} /><span class="lv">L{l[`${s}_level`]}</span>
                      {#if l[`${s}_shiny`]}<span class="shiny-star">★</span>{/if}
                    </span>
                  {:else}
                    <span class="dim">— no mon recorded</span>
                  {/if}
                </td>
              {/each}
              <td><span class="link-state {l.status}">{l.status}</span></td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </section>

  <section class="card">
    <h3>Areas</h3>
    <p class="card-sub">
      <code>pending_a</code> / <code>pending_b</code> mean one player has an encounter
      logged and the other has not reached that area yet — a per-player state, so it is
      named per player rather than as one shared "pending".
    </p>
    <div class="badge-row">
      {#each areas as [id, state] (id)}
        <span class="link-state {state}">{areaLabel(id)} · {state.replace('_', ' ')}</span>
      {/each}
    </div>
  </section>
</div>
