import { mount } from 'svelte';
import App from './App.svelte';
import './app.css';

/* slink.css hides funnotbun sprites until something chroma-keys their solid background
 * away (`img.mon-sprite[src*="funnotbun"]:not([data-bg-removed])`), so a page that
 * renders sprites without running that step shows blank cells and looks like the data is
 * missing. The vendored overlay-helpers.js already does the work and exposes it as
 * SLinkOverlay.processSprites; it runs once on DOMContentLoaded, which is before Svelte
 * has mounted anything. Re-run it whenever the DOM changes.
 *
 * Gen 1 hides the problem rather than avoiding it: its sprites come from PokeAPI, are
 * already transparent, and the CSS rule never matches them. */
/* setTimeout, not requestAnimationFrame: rAF does not fire in a background tab, so an
 * rAF-debounced observer that sets its `queued` latch before the frame that would clear
 * it stays latched forever and never fires again, even once the tab is foregrounded.
 * (Track A's watchSprites() has this bug.) */
function watchSprites() {
  const run = () => window.SLinkOverlay && window.SLinkOverlay.processSprites();
  let queued = false;
  new MutationObserver(() => {
    if (queued) return;
    queued = true;
    setTimeout(() => { queued = false; run(); }, 0);
  }).observe(document.body, { childList: true, subtree: true });
  run();
}

const app = mount(App, { target: document.getElementById('app') });
watchSprites();

export default app;
