<script>
  // The capability demo. Every column below either exists or does not — nothing
  // renders blank-because-the-cartridge-can't (brief §4).
  import MonCell from './MonCell.svelte';
  import { statusChips, hpClass, pct } from './lib/fmt.js';

  let { ctx } = $props();

  // abilities: true → column. false → NO column. null (rom_type not in
  // capabilities.json at all) → column present, cells read "unknown".
  const showAbility = $derived(ctx.abilities !== false);
  const abilityUnknown = $derived(ctx.abilities === null);
</script>

<div class="scroll-x">
  <table class="grid">
    <thead>
      <tr>
        <th>Mon</th>
        <th>Lv</th>
        <th>HP</th>
        <th>Status</th>
        {#if showAbility}<th>Ability</th>{/if}
        {#if ctx.heldItems}<th>Item</th>{/if}
        <th>Moves</th>
      </tr>
    </thead>
    <tbody>
      {#each ctx.party as m (m.key)}
        <tr>
          <td><MonCell mon={m} /></td>
          <td><span class="lv">L{m.level}</span></td>
          <td style="min-width:110px">
            <div class="hp-row" style="display:flex;align-items:center;gap:6px">
              <div class="hp-trk" style="min-width:52px">
                <div class="hp-fill {hpClass(m.hp, m.maxHP)}" style="width:{pct(m.hp, m.maxHP)}%"></div>
              </div>
              <span class="dim">{m.hp}/{m.maxHP}</span>
            </div>
          </td>
          <td>
            {#each statusChips(m.status_cond) as [txt, cls] (cls)}
              <span class="sc {cls}">{txt}</span>
            {:else}
              <span class="dim">—</span>
            {/each}
          </td>
          {#if showAbility}
            <td>
              {#if abilityUnknown}
                <span class="unk">unknown</span>
              {:else}
                {m.ability_name || '—'}
              {/if}
            </td>
          {/if}
          {#if ctx.heldItems}
            <td>{m.held_item_id ? `#${m.held_item_id}` : '—'}</td>
          {/if}
          <td>
            <span class="moves-mini">
              {#each m.move_details || [] as mv (mv.name)}
                <span class="mv mt-{mv.type_name || 'unknown'}" title="{mv.type_name} · {mv.power || '—'} pow">
                  {mv.name}
                </span>
              {/each}
            </span>
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>

{#if ctx.abilities === false}
  <p class="absent-note">
    No Ability column — {ctx.label} predates abilities
    (<code>capabilities.{ctx.capsKey}.abilities = false</code>).
  </p>
{/if}
{#if !ctx.heldItems}
  <p class="absent-note">
    No Item column — no mon in this player's payload carries a non-zero
    <code>held_item_id</code>. Decided from data, not from capabilities (brief §4).
  </p>
{/if}
