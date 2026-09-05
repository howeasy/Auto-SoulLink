<script>
  import { app, bothPlayers } from '../lib/store.svelte.js';
  import PartyTable from '../PartyTable.svelte';

  const players = $derived(bothPlayers());
  const st = $derived(app.status);
  const events = $derived((st?.recent_events || []).slice(0, 40));
  const alive = $derived((st?.links || []).filter((l) => l.status === 'alive').length);
  const dead = $derived((st?.links || []).filter((l) => l.status === 'dead').length);
</script>

<div class="pane">
  <div class="stat-row card">
    <span class="st"><b>{alive}</b><span>links alive</span></span>
    <span class="st"><b>{dead}</b><span>links dead</span></span>
    <span class="st"><b>{st?.attempts_count ?? '—'}</b><span>attempt</span></span>
    <span class="st"><b>{(st?.killfeed || []).length}</b><span>memorial</span></span>
  </div>

  <!-- Two symmetric player columns. Everything inside one column is resolved from
       THAT player's cartridge — no shared tables (brief §5). -->
  <div class="cols">
    {#each players as c (c.side)}
      <section class="card">
        <h3>Player {c.side.toUpperCase()} · {c.p?.trainer_name} · {c.label}</h3>
        <p class="card-sub">
          {c.p?.current_area_display || '—'}
          · {c.p?.connected ? 'connected' : `offline (last seen ${c.p?.last_seen || '—'})`}
          {#if c.capsInferred}
            · <span class="unk">capabilities inferred from “{c.capsKey}”</span>
          {:else if !c.capsFound}
            · <span class="unk">no capability record for “{c.romType}”</span>
          {/if}
        </p>

        <PartyTable ctx={c} />

        <!-- Battle panel exists only while THIS player is in a battle. -->
        {#if c.p?.battle_state?.in_battle}
          <h3 style="margin-top:1em">In battle</h3>
          <dl class="kv">
            <dt>Kind</dt>
            <dd>{c.p.battle_state.is_trainer_battle ? 'Trainer' : 'Wild'}{c.p.battle_state.is_doubles ? ' · Doubles' : ''}</dd>
            <dt>Opponent</dt>
            <dd>{c.p.battle_state.opponent_name || c.p.battle_state.opponent_class || 'unnamed'}</dd>
          </dl>

          <!-- Stat stages: `stat_stage_labels` is the ordered label list and a blank
               label suppresses that badge (brief §4). It reads null on this
               checkout, which is UNKNOWN, not "no stat stages". -->
          {#if c.statStageLabels === null}
            <p class="absent-note">
              Stat-stage badges withheld — <code>stat_stage_labels</code> is
              <span class="unk">unknown</span> for {c.capsKey || c.romType}. Rendering a
              guessed label set would misreport Gen 1's single Special as Sp.Atk + Sp.Def.
            </p>
          {:else if c.statStageLabels.length}
            <div class="stat-stages-row">
              {#each c.statStageLabels as lbl, i (i)}
                {#if lbl}<span class="stat-stage ss-up">{lbl}</span>{/if}
              {/each}
            </div>
          {/if}
        {/if}

        <!-- Native in-game info panel: a companion-patch capability, resolved per
             player, because one player may have patched and the other not. -->
        {#if c.infoPanel === true}
          <h3 style="margin-top:1em">Native info panel</h3>
          <dl class="kv">
            <dt>Width</dt>
            <dd>{c.caps.info_panel_width ?? ''}{#if c.caps.info_panel_width == null}<span class="unk">unknown</span>{/if}</dd>
            <dt>Source</dt>
            <dd>companion ROM patch ({c.capsKey})</dd>
          </dl>
        {:else if c.infoPanel === null}
          <p class="absent-note">Native info panel: <span class="unk">unknown</span> for “{c.romType}”.</p>
        {/if}

        <h3 style="margin-top:1em">Badges</h3>
        <div class="badge-row">
          {#if c.badges}
            {#each c.badges as b, i (b)}
              <span class="bdg" class:earned={i < (c.p?.badges || 0)}>{b}</span>
            {/each}
          {:else}
            <span class="unk">badge list unknown</span>
          {/if}
        </div>
      </section>
    {/each}
  </div>

  <section class="card">
    <h3>Events</h3>
    <div class="feed">
      {#each events as e, i (i)}
        <div class="feed-row">
          <span class="ts">{(e.ts || '').slice(11, 19)}</span>
          <span class="who" style="color:var(--c-{e.player === 'a' ? 'link' : 'pend'})">
            {(e.player || '·').toUpperCase()}
          </span>
          <span>{e.text}</span>
        </div>
      {/each}
    </div>
  </section>
</div>
