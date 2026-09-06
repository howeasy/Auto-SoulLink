<script>
  import { app, bothPlayers } from '../lib/store.svelte.js';
  import MonCell from '../MonCell.svelte';
  import { areaLabel } from '../lib/fmt.js';

  const players = $derived(bothPlayers());
  const fallen = $derived(app.status?.killfeed || []);
  const half = (l, s) => ({
    nickname: l[`${s}_nickname`], species_name: l[`${s}_species_name`],
    species_id: l[`${s}_species`], sprite_html: l[`${s}_sprite_html`],
  });
</script>

<div class="pane">
  <section class="card">
    <h3>Memorial · {fallen.length} pairs lost</h3>
    {#if !fallen.length}
      <p class="absent-note">No deaths yet.</p>
    {:else}
      <div class="scroll-x">
        <table class="grid">
          <thead>
            <tr>
              <th>Area</th>
              <th>{players[0].p?.trainer_name || 'A'}</th>
              <th>{players[1].p?.trainer_name || 'B'}</th>
              <th>Cause</th>
              <th>Fell</th>
            </tr>
          </thead>
          <tbody>
            {#each fallen as k (k.a_key + k.b_key)}
              <tr>
                <td class="lk-area">{k.area_display || areaLabel(k.area_id)}</td>
                {#each ['a', 'b'] as s (s)}
                  <td>
                    {#if k[`${s}_species`]}
                      <span style="display:flex;align-items:center;gap:8px;opacity:.72">
                        <MonCell mon={half(k, s)} /><span class="lv">L{k[`${s}_level`]}</span>
                      </span>
                    {:else}
                      <span class="dim">— no mon recorded</span>
                    {/if}
                  </td>
                {/each}
                <td>
                  {k.cause}{#if k.killer} · {k.killer}{/if}
                  <span class="dim"> (started by {(k.initiating_player || '?').toUpperCase()})</span>
                </td>
                <td class="dim">{(k.killed_at || '').slice(0, 16).replace('T', ' ')}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>
</div>
