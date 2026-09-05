<script>
  import { app, loadGen, currentRun, applyTheme, applyDensity, TABS } from './lib/store.svelte.js';
  import Rail from './Rail.svelte';
  import RunHeader from './RunHeader.svelte';
  import TabLive from './tabs/TabLive.svelte';
  import TabLinks from './tabs/TabLinks.svelte';
  import TabBoxes from './tabs/TabBoxes.svelte';
  import TabMemorial from './tabs/TabMemorial.svelte';
  import TabSetup from './tabs/TabSetup.svelte';

  const PANES = {
    Live: TabLive, Links: TabLinks, Boxes: TabBoxes,
    Memorial: TabMemorial, Setup: TabSetup,
  };

  $effect(() => {
    document.body.classList.toggle('density-compact', app.density === 'compact');
  });

  applyTheme(app.theme);
  applyDensity(app.density);
  loadGen('gen3');

  const run = $derived(currentRun());
  const Pane = $derived(PANES[app.tab]);
</script>

<div class="ws">
  <Rail />
  <main class="main">
    {#if app.error}
      <div class="pane"><div class="banner"><b>Could not load fixtures.</b> {app.error}</div></div>
    {:else if app.loading || !app.status}
      <div class="pane"><div class="banner">Loading fixtures…</div></div>
    {:else}
      <RunHeader {run} />
      <nav class="tabs">
        {#each TABS as t (t)}
          <button class:active={app.tab === t} onclick={() => (app.tab = t)}>{t}</button>
        {/each}
      </nav>
      <Pane />
    {/if}
  </main>
</div>
