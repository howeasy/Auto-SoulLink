<script>
  import { spriteInitials } from './lib/fmt.js';
  let { mon } = $props();
</script>

<span class="nm-cell">
  {#if mon.sprite_html}
    <!-- The payload's own markup, injected verbatim. Gen 3 funnotbun sprites are hidden
         by slink.css until overlay-helpers strips their solid background; App.svelte
         re-runs SLinkOverlay.processSprites() after every render to do that. -->
    <span class="sprite-slot">{@html mon.sprite_html}</span>
  {:else}
    <!-- pc_boxes entries carry no sprite_html (and no species_name) — the placeholder
         is the honest render of what the payload holds, not a workaround. -->
    <span class="mini-sprite" title="species #{mon.species_id}">
      {spriteInitials(mon.species_name)}<small>#{mon.species_id}</small>
    </span>
  {/if}
  <span class="txt">
    <b>{mon.nickname || mon.species_name || `#${mon.species_id}`}</b>
    <span class="sp">{mon.species_name || `species #${mon.species_id} · name not in payload`}</span>
  </span>
</span>
