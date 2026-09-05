<script>
  import { bothPlayers } from '../lib/store.svelte.js';
  import MonCell from '../MonCell.svelte';

  const players = $derived(bothPlayers());

  function byBox(p) {
    const m = new Map();
    for (const mon of p?.pc_boxes || []) {
      if (!m.has(mon.box)) m.set(mon.box, []);
      m.get(mon.box).push(mon);
    }
    return [...m.entries()].sort((x, y) => x[0] - y[0]);
  }
</script>

<div class="pane">
  <div class="cols">
    {#each players as c (c.side)}
      <section class="card">
        <h3>Boxes · {c.p?.trainer_name} · {c.label}</h3>
        <!-- Box capacity comes from mons_per_box, never a hardcoded 30 (brief §4).
             It reads null on this checkout: unknown, so we do not draw a grid of
             empty slots we cannot size. -->
        <p class="card-sub">
          Capacity per box:
          {#if c.monsPerBox == null}
            <span class="unk">unknown</span> — <code>mons_per_box</code> is null for
            {c.capsKey || c.romType}; no slot grid is drawn rather than assuming 30.
          {:else}
            {c.monsPerBox}
          {/if}
          · Memorial box #{c.caps.memorial_box_index ?? '?'}
        </p>

        {#each byBox(c.p) as [box, mons] (box)}
          <h3 style="margin-top:.8em">Box {box + 1} · {mons.length} stored</h3>
          <table class="grid">
            <thead>
              <tr>
                <th>Slot</th><th>Mon</th>
                {#if c.heldItems}<th>Item</th>{/if}
              </tr>
            </thead>
            <tbody>
              {#each mons as m (m.key)}
                <tr>
                  <td class="dim">{m.slot + 1}</td>
                  <td><MonCell mon={m} /></td>
                  {#if c.heldItems}<td>{m.held_item_id ? `#${m.held_item_id}` : '—'}</td>{/if}
                </tr>
              {/each}
            </tbody>
          </table>
        {:else}
          <p class="absent-note">Nothing boxed.</p>
        {/each}
      </section>
    {/each}
  </div>
</div>
