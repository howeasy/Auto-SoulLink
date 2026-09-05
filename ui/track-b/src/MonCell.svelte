<script>
  import { spriteInitials } from './lib/fmt.js';
  let { mon } = $props();
</script>

<span class="nm-cell">
  <!-- No remote sprite: payload sprite_html points at raw.githubusercontent.com and
       the mockup must render with no network (brief §8.3). -->
  <span class="mini-sprite" title="species #{mon.species_id}">
    {spriteInitials(mon.species_name)}<small>#{mon.species_id}</small>
  </span>
  <span class="txt">
    <b>{mon.nickname || mon.species_name || `#${mon.species_id}`}</b>
    <!-- pc_boxes entries carry species_id but no species_name; say so rather than
         printing an empty line where the species belongs. -->
    <span class="sp">{mon.species_name || `species #${mon.species_id} · name not in payload`}</span>
  </span>
</span>
