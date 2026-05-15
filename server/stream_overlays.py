"""Stream overlay HTML templates for OBS browser sources.

All stream overlay CSS, JS, and HTML templates live here.
The SLinkServer handlers in server.py import the public symbols.
"""
# ── Stream overlay templates ─────────────────────────────────────────────────
# Self-contained HTML pages for OBS browser sources. Each fetches /api/status
# and renders only the relevant subset. Transparent background by default.
#
# !! IMPORTANT — NO SSE IN STREAM OVERLAYS !!
# Stream overlays MUST use polling (/api/status every 2 s via setInterval),
# never EventSource / SSE. Chrome enforces a hard limit of 6 simultaneous
# connections per origin. The main status page already holds one SSE
# connection; if overlays opened as additional browser sources also opened
# SSE connections they would exhaust the pool and stall ALL requests from
# that origin (including the polling fetches themselves).
#
# The shared polling loop lives in _STREAM_SHARED_JS → init() → setInterval.
# Each overlay template only needs to define a render(data) function that
# receives the parsed /api/status JSON and updates #root.innerHTML.
#
# !! IMPORTANT — AVOID UNNECESSARY innerHTML REWRITES !!
# Overlays that display external images (e.g. PokeAPI badge sprites) MUST
# gate their render on a state-change check. Replacing innerHTML every 2 s
# forces the browser to re-fetch/re-paint images even when nothing changed,
# causing visible flicker. Cache a state key from the previous render and
# return early when it is unchanged (see _STREAM_BADGES_JS for the pattern).

_STREAM_SHARED_CSS = """
  :root {
    --c-alive:#3de85a; --c-dead:#f03838; --c-pend:#f8a020;
    --c-gold:#f8d030;  --c-txt:#e6e6e6;  --c-dim:rgba(220,220,220,.4);
    --c-bg:rgba(7,9,16,.90); --c-card:rgba(255,255,255,.038);
    --c-edge:rgba(255,255,255,.09); --c-sep:rgba(255,255,255,.06);
    --px:'Press Start 2P','Courier New',monospace;
  }
  body.theme-light {
    --c-alive:#1a9a38; --c-dead:#c82020; --c-pend:#c86010;
    --c-gold:#1a5fb0;  --c-txt:#18182a;  --c-dim:rgba(24,24,42,.5);
    --c-bg:rgba(238,242,252,.92); --c-card:rgba(0,0,0,.028);
    --c-edge:rgba(0,0,0,.10); --c-sep:rgba(0,0,0,.07);
  }
  body.theme-transparent {
    --c-bg:transparent; --c-card:transparent;
    --c-edge:transparent; --c-sep:transparent;
  }
  body.theme-transparent #root{border:none}
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  html,body{width:100%;height:100%;overflow:hidden}
  body{background:transparent;font-family:system-ui,'Segoe UI',sans-serif;font-size:clamp(14px,4.5vmin,22px);color:var(--c-txt);-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale}
  #root{width:100%;height:100%;background:var(--c-bg);border:1px solid var(--c-edge);border-top:2px solid var(--c-gold);padding:clamp(8px,1.6vmin,18px);overflow:hidden;display:flex;flex-direction:column;gap:clamp(4px,.8vmin,10px);transform:translateZ(0);will-change:transform}
  /* Widget title — Press Start 2P: fixed 10px so all overlays render the same regardless of OBS window size */
  .wtitle{font-family:var(--px);font-size:10px;-webkit-font-smoothing:none;color:var(--c-gold);letter-spacing:.06em;padding-bottom:clamp(4px,.7vmin,9px);border-bottom:1px solid var(--c-sep);flex-shrink:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  /* Sprites */
  .mon-sprite{width:clamp(38px,6.5vmin,58px);aspect-ratio:1;image-rendering:pixelated;image-rendering:crisp-edges;flex-shrink:0}
  .lk-row .mon-sprite{width:clamp(30px,5vmin,46px)}
  /* HP system */
  .hp-row{display:flex;align-items:center;gap:clamp(3px,.55vmin,7px);margin-top:clamp(2px,.35vmin,5px)}
  .hp-lbl{font-size:.78em;color:var(--c-dim);flex-shrink:0}
  .hp-trk{flex:1;min-width:clamp(24px,4vw,70px);height:clamp(5px,.75vmin,8px);background:rgba(128,128,128,.18);border-radius:99px;overflow:hidden}
  .hp-fill{height:100%;border-radius:99px;transition:width .4s ease}
  .hp-h{background:var(--c-alive)}.hp-m{background:#f0c030}.hp-l{background:var(--c-dead);box-shadow:0 0 4px var(--c-dead)}
  .hp-pct{font-size:.83em;min-width:3.3ch;text-align:right;flex-shrink:0;opacity:.62}
  .lv{font-size:.8em;background:rgba(128,128,128,.15);padding:1px 5px;border-radius:3px;flex-shrink:0;white-space:nowrap;opacity:.8}
  .sc{display:inline-block;padding:1px 5px;border-radius:3px;font-size:.72em;font-weight:bold;white-space:nowrap;flex-shrink:0;line-height:1.4}
  .sc-slp{background:#7a7a7a;color:#fff}.sc-psn{background:#c040c0;color:#fff}.sc-brn{background:#d06020;color:#fff}
  .sc-frz{background:#5ab8e4;color:#fff}.sc-par{background:#c8a800;color:#000}.sc-tox{background:#6a00aa;color:#fff}
  .stat-stage{display:inline-block;padding:1px 5px;border-radius:3px;font-size:0.7em;font-weight:bold;white-space:nowrap;margin:1px 2px;border:1px solid}
  .ss-up{background:rgba(46,204,113,0.15);color:#5af09a;border-color:rgba(46,204,113,0.55)}.ss-dn{background:rgba(231,76,60,0.15);color:#ff7f72;border-color:rgba(231,76,60,0.55)}
  .stat-stages-row{padding:2px 0 1px 0;display:flex;flex-wrap:wrap;gap:2px}
  /* Party list — fainted: opacity only, no filter (filter rasterises the whole layer → blurs text) */
  .p-list{display:flex;flex-direction:column;gap:clamp(3px,.55vmin,7px);flex:1;overflow:hidden}
  .mc{display:flex;align-items:center;gap:clamp(6px,1.1vmin,13px);padding:clamp(4px,.7vmin,9px) clamp(7px,1.1vmin,13px);background:var(--c-card);border-radius:4px;border-left:3px solid rgba(128,128,128,.18);min-width:0}
  .mc.bh{border-left-color:var(--c-alive)}.mc.bm{border-left-color:#f0c030}.mc.bl,.mc.fnt{border-left-color:var(--c-dead)}.mc.fnt{opacity:.45}
  .mc.fnt .mon-sprite{filter:grayscale(60%)}
  .m-info{flex:1;min-width:0}
  .m-name{font-size:1em;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.3}
  .m-name .sp{font-weight:400;opacity:.48;font-size:.87em}
  .fnt-tag{font-size:.72em;background:var(--c-dead);color:#fff;padding:1px 6px;border-radius:3px;margin-left:4px;vertical-align:middle}
  /* Links list */
  .lk-list{display:flex;flex-direction:column;gap:clamp(3px,.55vmin,6px);flex:1;overflow:hidden}
  .lk-row{display:flex;align-items:center;gap:clamp(4px,.8vmin,10px);padding:clamp(4px,.7vmin,8px) clamp(7px,1.1vmin,13px);background:var(--c-card);border-radius:4px;border-left:3px solid rgba(128,128,128,.18);min-width:0}
  .lk-row.la{border-left-color:var(--c-alive)}.lk-row.ld{border-left-color:var(--c-dead);opacity:.45}
  .lk-row.ld .mon-sprite{filter:grayscale(60%)}
  .lk-half{flex:1;min-width:0;display:flex;align-items:center;gap:clamp(3px,.55vmin,7px)}.lk-half.r{flex-direction:row-reverse}
  .lk-nm{flex:1;min-width:0;font-size:.9em;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .lk-half.r .lk-nm{text-align:right}
  .lk-lv{font-size:.82em;opacity:.5;flex-shrink:0;white-space:nowrap}
  .lk-div{flex-shrink:0;font-size:1.1em;opacity:.3;color:var(--c-gold)}
  /* Deaths counter */
  .d-wrap{display:flex;align-items:center;justify-content:center;width:100%;flex:1;min-height:0}
  .d-grid{display:flex;gap:clamp(18px,9vw,80px);align-items:center}
  .d-box{text-align:center;line-height:1}
  .d-num{font-family:var(--px);font-size:clamp(1.8em,8vmin,4.5em);line-height:1;display:block;-webkit-font-smoothing:none}
  .d-lbl{font-family:var(--px);font-size:clamp(8px,1.6vmin,14px);-webkit-font-smoothing:none;opacity:.5;letter-spacing:.07em;display:block;margin-top:clamp(6px,1.1vmin,12px)}
  .d-alive .d-num{color:var(--c-alive);text-shadow:0 0 20px rgba(61,232,90,.45)}.d-dead .d-num{color:var(--c-dead);text-shadow:0 0 20px rgba(240,56,56,.45)}
  .d-attempts .d-num{color:var(--c-gold);text-shadow:0 0 20px rgba(248,208,48,.45)}
  /* Event feed */
  .e-list{display:flex;flex-direction:column;flex:1;overflow:hidden}
  .e-row{display:flex;align-items:baseline;gap:clamp(5px,.9vmin,11px);padding:clamp(3px,.5vmin,6px) 0;border-bottom:1px solid var(--c-sep);overflow:hidden;flex-shrink:0}
  .e-ts{font-family:var(--px);font-size:clamp(7px,1.3vmin,11px);-webkit-font-smoothing:none;opacity:.36;flex-shrink:0;white-space:nowrap;padding-top:1px;min-width:4.5em}
  .e-who{font-family:var(--px);font-size:clamp(7px,1.3vmin,11px);-webkit-font-smoothing:none;font-weight:bold;flex-shrink:0;white-space:nowrap;padding-top:1px}
  .e-msg{flex:1;min-width:0;font-size:.93em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .ec{color:var(--c-alive)}.ef{color:var(--c-dead)}.ew{color:#f87020;font-weight:700}.en{color:var(--c-pend)}.ea{color:#5ac8f8}.el{color:var(--c-alive);font-weight:700}.ed{color:var(--c-dead);font-weight:700}.ev{color:#f8a030;font-weight:700}.ek{color:#c080f8}.eh{opacity:.32}
  /* Area stats — reuses d-* death/attempts counter style */
  .a-pend .d-num{color:var(--c-pend);text-shadow:0 0 20px rgba(248,160,32,.45)}
  /* Badges */
  .bdg-wrap{display:flex;flex:1;align-items:center;justify-content:center}
  .bdg-player{display:flex;flex-direction:column;align-items:center;gap:clamp(4px,.8vmin,9px)}
  .bdg-strip{display:flex;gap:clamp(3px,.6vw,8px);flex-wrap:wrap;justify-content:center}
  .bdg-img{width:clamp(24px,4.5vmin,42px);aspect-ratio:1;image-rendering:pixelated;image-rendering:crisp-edges;transition:opacity .2s}
  .bdg-img.on{opacity:1}.bdg-img.off{opacity:.1;filter:grayscale(100%)}

  /* ─── Links widget (redesigned) ──────────────────────────────────────── */
  /* Alive pair card */
  .lk-card{background:var(--c-card);border-radius:5px;border-left:3px solid var(--c-alive);padding:clamp(4px,.7vmin,9px) clamp(6px,1.1vmin,13px);display:flex;flex-direction:column;gap:clamp(2px,.4vmin,5px)}
  .lk-area{font-size:.72em;color:var(--c-gold);opacity:.75;letter-spacing:.04em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .lk-pair{display:flex;align-items:center;gap:clamp(4px,.7vmin,8px)}
  /* Dead section */
  .lk-dead-hdr{font-family:var(--px);font-size:clamp(7px,1.3vmin,10px);-webkit-font-smoothing:none;color:var(--c-dead);opacity:.45;text-align:center;letter-spacing:.1em;padding:clamp(2px,.4vmin,4px) 0;flex-shrink:0}
  .lk-dead-row{display:flex;align-items:center;gap:clamp(4px,.7vmin,8px);padding:clamp(2px,.35vmin,3px) clamp(6px,1vmin,12px);opacity:.35;flex-shrink:0}
  .lk-dead-x{color:var(--c-dead);flex-shrink:0;font-size:.85em}
  .lk-dead-nm{flex:1;min-width:0;font-size:.82em;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .lk-dead-nm.r{text-align:right}
  .lk-dead-sep{opacity:.25;color:var(--c-gold);flex-shrink:0}

  /* ─── Linked Party widget ─────────────────────────────────────────────── */
  .lp-list{display:flex;flex-direction:column;gap:clamp(4px,.8vmin,10px);flex:1;overflow:hidden}
  .lp-card{background:var(--c-card);border-radius:6px;border-left:3px solid var(--c-alive);padding:clamp(5px,.9vmin,11px) clamp(7px,1.2vmin,14px);display:flex;flex-direction:column;gap:clamp(3px,.5vmin,6px)}
  .lp-card.ld{border-left-color:var(--c-dead);opacity:.5}
  .lp-area{font-size:.72em;color:var(--c-gold);opacity:.75;letter-spacing:.04em;text-transform:capitalize;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .lp-mons{display:flex;align-items:center;gap:clamp(4px,.8vmin,10px)}
  .lp-side{flex:1;min-width:0;display:flex;align-items:center;gap:clamp(4px,.7vmin,9px)}
  /* lp-r: Side B — no row-reverse; DOM order [Info][Sprite] already mirrors Side A */
  .lp-info{flex:1;min-width:0}
  .lp-info.lp-ir{text-align:right}
  .lp-nm{font-size:.9em;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.2;margin-bottom:clamp(2px,.35vmin,4px)}
  .lp-r .hp-trk{transform:scaleX(-1)}
  .lp-sep{flex-shrink:0;font-size:1.2em;opacity:.35;color:var(--c-gold)}

  /* ─── Boxed Links widget ──────────────────────────────────────────────── */
  .bl-list{display:flex;flex-direction:column;gap:clamp(4px,.8vmin,10px);flex:1;overflow:hidden}
  .bl-card{background:var(--c-card);border-radius:6px;border-left:3px solid var(--c-gold);padding:clamp(5px,.9vmin,11px) clamp(7px,1.2vmin,14px);display:flex;flex-direction:column;gap:clamp(3px,.5vmin,6px)}
  .bl-area{font-size:.72em;color:var(--c-gold);opacity:.75;letter-spacing:.04em;text-transform:capitalize;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .bl-row{display:flex;align-items:center;gap:clamp(4px,.8vmin,10px)}
  .bl-side{flex:1;min-width:0;display:flex;align-items:center;gap:clamp(4px,.7vmin,9px)}
  /* bl-r: Side B — no row-reverse; DOM order [Info][Sprite] already mirrors Side A */
  .bl-bx{}
  .bl-info{flex:1;min-width:0;text-align:right;padding-right:clamp(4px,.7vmin,8px)}
  .bl-info.bl-ir{text-align:left;padding-right:0;padding-left:clamp(4px,.7vmin,8px)}
  .bl-nm{font-size:.9em;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.2}
  .bl-lv{font-size:.7em;opacity:.65;line-height:1.3}
  .bl-tag{display:inline-block;font-family:var(--px);font-size:clamp(5px,.9vmin,8px);-webkit-font-smoothing:none;color:var(--c-gold);opacity:.6;letter-spacing:.06em;line-height:1.4}
  .bl-sep{flex-shrink:0;font-size:1.1em;opacity:.3;color:var(--c-gold)}
  .bl-side .mon-sprite{width:clamp(28px,5vmin,44px)}

  /* Boxed Links compact grid (sprites-only when many pairs) */
  .bl-grid{display:flex;flex-wrap:wrap;gap:clamp(4px,.8vmin,10px);flex:1;overflow:hidden;align-content:flex-start;justify-content:center}
  .bl-gpair{display:flex;align-items:center;gap:clamp(3px,.5vmin,6px);background:var(--c-card);border-radius:5px;padding:clamp(3px,.5vmin,7px) clamp(5px,.9vmin,10px)}
  .bl-gpair .mon-sprite{width:clamp(32px,5.5vmin,50px)}
  .bl-garr{flex-shrink:0;font-size:.9em;opacity:.3;color:var(--c-gold)}

  /* thin-v overrides for boxed links */
  body.ltv .bl-list{gap:clamp(2px,.5vw,5px)}
  body.ltv .bl-card{padding:clamp(3px,2vw,7px) clamp(3px,2vw,7px);gap:clamp(1px,1vw,4px)}
  body.ltv .bl-area{font-size:clamp(7px,4vw,10px)}
  body.ltv .bl-nm{font-size:clamp(9px,5.5vw,13px)}
  body.ltv .bl-lv{font-size:clamp(7px,4vw,10px)}
  body.ltv .bl-side .mon-sprite{width:clamp(24px,20vw,40px)!important;height:auto!important;aspect-ratio:unset!important}

  /* ─── Horizontal layout mode  (body.lh via ?layout=h) ─────────────── */
  /* Party: 6 cards side-by-side in a row */
  body.lh .p-list{flex-direction:row;align-items:stretch;overflow:hidden;gap:clamp(2px,.35vmin,4px)}
  body.lh .mc{flex-direction:column;align-items:center;flex:1;min-width:0;text-align:center;gap:clamp(1px,.25vmin,3px)}
  body.lh .m-info{display:flex;flex-direction:column;align-items:center;width:100%}
  body.lh .m-name{text-align:center;font-size:clamp(7px,1.05vmin,10px)}
  body.lh .m-name .sp{display:none}
  body.lh .fnt-tag{display:block;margin:2px auto 0}
  body.lh .hp-row{justify-content:center;flex-wrap:wrap;gap:clamp(2px,.3vmin,4px)}
  body.lh .hp-lbl{display:none}
  body.lh .lv{margin-top:1px}
  /* Areas: already centered d-grid layout — no horizontal override needed */
  /* Links: cards wrap into a grid */
  body.lh .lk-list{flex-direction:row;flex-wrap:wrap;align-content:flex-start;gap:clamp(2px,.4vmin,5px)}
  body.lh .lk-card{flex:0 0 auto;min-width:clamp(140px,22vw,220px)}

  /* ─── Thin-H: constrained HEIGHT (~100-200px), wide width ──────────── */
  /* Use ?layout=thin-h  — ideal for bottom/top-of-stream bars             */
  body.lth{padding:clamp(3px,2vh,8px) clamp(5px,1vw,14px);overflow:hidden}
  body.lth .wtitle{font-size:10px;-webkit-font-smoothing:none;margin-bottom:clamp(2px,.5vh,5px)}
  /* Party thin-h: row of cards */
  body.lth .p-list{flex-direction:row;align-items:stretch;gap:clamp(2px,.5vw,6px);overflow:hidden}
  body.lth .mc{flex-direction:column;align-items:center;justify-content:center;flex:1;min-width:0;padding:clamp(3px,2vh,8px) clamp(3px,.6vw,8px);gap:clamp(2px,.5vh,5px)}
  body.lth .m-name{display:none}
  body.lth .fnt-tag{font-size:clamp(5px,1vh,8px);padding:0 2px}
  /* Sprite: height tracks the constrained vh dimension — unset aspect-ratio */
  body.lth .mon-sprite{height:clamp(55px,50vh,100px)!important;width:auto!important;aspect-ratio:unset!important}
  /* hp-row stays ROW (not column) — hp-trk flex:1 fills width, not height */
  body.lth .hp-row{flex-direction:row;margin-top:0;gap:clamp(2px,.4vw,5px)}
  body.lth .hp-lbl{display:none}
  body.lth .hp-trk{height:clamp(5px,4vh,9px);min-width:0}
  body.lth .lv{flex-shrink:0;font-size:clamp(9px,7vh,13px);white-space:nowrap;line-height:1;opacity:.75}
  /* Linked-party thin-h: pairs in a row */
  body.lth .lp-list{flex-direction:row;gap:clamp(3px,.6vw,8px);overflow:hidden}
  body.lth .lp-card{flex:1;min-width:0;flex-direction:row;align-items:center;padding:clamp(3px,2vh,8px) clamp(4px,.8vw,10px);gap:clamp(4px,.7vw,9px)}
  body.lth .lp-area{display:none}
  body.lth .lp-mons{flex:1;min-width:0;gap:clamp(4px,.7vw,9px)}
  body.lth .lp-nm{font-size:clamp(10px,8vh,14px);margin-bottom:clamp(2px,.4vh,4px)}
  body.lth .lp-side .mon-sprite,body.lth .lp-side img.mon-sprite{height:clamp(48px,48vh,90px)!important;width:auto!important;aspect-ratio:unset!important}
  body.lth .lp-info .hp-row{margin-top:0;flex-direction:row}
  body.lth .lp-info .hp-trk{height:clamp(5px,4vh,9px)}
  /* Links thin-h: alive cards in a row */
  body.lth .lk-list{flex-direction:row;flex-wrap:nowrap;gap:clamp(3px,.6vw,8px);overflow:hidden}
  body.lth .lk-card{flex:1;min-width:0;padding:clamp(3px,2vh,7px) clamp(4px,.8vw,9px);gap:clamp(1px,.3vh,3px)}
  body.lth .lk-area{display:none}
  body.lth .lk-half .mon-sprite{height:clamp(42px,44vh,80px)!important;width:auto!important;aspect-ratio:unset!important}
  body.lth .lk-nm{font-size:clamp(9px,7vh,13px)}
  body.lth .lk-lv{font-size:clamp(6px,1.1vh,9px)}
  body.lth .lk-dead-hdr{display:none}
  body.lth .lk-dead-row{padding:clamp(2px,.4vh,5px) clamp(4px,.8vw,9px)}

  /* ─── Thin-V: constrained WIDTH (~100-200px), tall height ──────────── */
  /* Use ?layout=thin-v  — ideal for left/right sidebars                  */
  body.ltv{padding:clamp(3px,2vw,8px) clamp(4px,2vw,9px);overflow:hidden}
  body.ltv .wtitle{font-size:10px;-webkit-font-smoothing:none;margin-bottom:clamp(2px,.5vw,5px)}
  /* Party thin-v: stack of horizontal rows, sprite + hp side by side */
  body.ltv .p-list{flex-direction:column;gap:clamp(2px,.5vw,5px);overflow:hidden}
  body.ltv .mc{flex-direction:row;align-items:center;padding:clamp(3px,2vw,7px) clamp(3px,2vw,7px);gap:clamp(3px,2vw,7px)}
  body.ltv .m-name{font-size:clamp(11px,7vw,15px);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  body.ltv .m-name .sp{display:none}
  body.ltv .hp-pct{display:none}
  body.ltv .m-info{flex:1;min-width:0;display:flex;flex-direction:column;gap:clamp(2px,.4vw,4px)}
  body.ltv .hp-row{margin-top:0;gap:clamp(2px,1.5vw,5px)}
  body.ltv .hp-lbl{display:none}
  body.ltv .hp-trk{height:clamp(5px,3vw,9px)}
  body.ltv .lv{font-size:clamp(9px,5.5vw,13px);white-space:nowrap;opacity:.75;line-height:1}
  /* Sprite: width tracks the constrained vw dimension — unset aspect-ratio */
  body.ltv .mon-sprite{width:clamp(32px,28vw,56px)!important;height:auto!important;aspect-ratio:unset!important;flex-shrink:0}
  body.ltv .fnt-tag{font-size:clamp(6px,3.5vw,9px);padding:0 2px}
  /* Linked-party thin-v: compact pair rows */
  body.ltv .lp-list{flex-direction:column;gap:clamp(2px,.5vw,6px);overflow:hidden}
  body.ltv .lp-card{padding:clamp(3px,2vw,7px) clamp(3px,2vw,7px);gap:clamp(2px,1.5vw,5px)}
  body.ltv .lp-area{font-size:clamp(8px,5vw,12px)}
  body.ltv .lp-mons{gap:clamp(3px,2vw,8px)}
  body.ltv .lp-nm{font-size:clamp(10px,6.5vw,14px);margin-bottom:1px}
  body.ltv .lp-side .mon-sprite,body.ltv .lp-side img.mon-sprite{width:clamp(26px,22vw,44px)!important;height:auto!important;aspect-ratio:unset!important}
  body.ltv .lp-info .hp-row{margin-top:0}
  body.ltv .lp-info .hp-trk{height:clamp(5px,3vw,9px)}
  body.ltv .lp-sep{font-size:.9em}
  /* Links thin-v: compact card stack */
  body.ltv .lk-list{flex-direction:column;gap:clamp(2px,.5vw,5px);overflow:hidden}
  body.ltv .lk-card{padding:clamp(2px,1.5vw,6px) clamp(3px,2vw,7px);gap:clamp(1px,1vw,4px)}
  body.ltv .lk-area{font-size:clamp(8px,4.5vw,11px)}
  body.ltv .lk-half .mon-sprite{width:clamp(24px,20vw,40px)!important;height:auto!important;aspect-ratio:unset!important}
  body.ltv .lk-nm{font-size:clamp(9px,5.5vw,13px)}
  body.ltv .lk-lv{display:none}
  body.ltv .lk-dead-hdr{font-size:clamp(7px,4vw,10px)}
  body.ltv .lk-dead-nm{font-size:clamp(9px,5.5vw,13px)}

  /* ─── Ticker overlay ──────────────────────────────────────────────────── */
  @keyframes ticker { from{transform:translateX(0)} to{transform:translateX(-50%)} }
  .ticker-mask{overflow:hidden;flex:1;min-width:0}
  .ticker-track{display:inline-flex;gap:clamp(8px,1.5vw,20px);animation:ticker 40s linear infinite;white-space:nowrap;will-change:transform}
  .t-pill{display:inline-flex;align-items:baseline;gap:clamp(4px,.8vmin,9px);padding:clamp(3px,.5vmin,6px) clamp(7px,1.2vmin,14px);background:var(--c-card);border-radius:4px;flex-shrink:0}

  /* ─── Memorial stream overlay ─────────────────────────────────────────── */
  @keyframes memorial-scroll { from{transform:translateY(0)} to{transform:translateY(-50%)} }
  .mem-scroll-mask{overflow:hidden;flex:1;min-height:0}

  /* ─── Shiny alert overlay ─────────────────────────────────────────────── */
  @keyframes shiny-pop{0%{opacity:0;transform:scale(.3) rotate(-10deg)}60%{transform:scale(1.1) rotate(2deg)}100%{opacity:1;transform:scale(1) rotate(0)}}
  @keyframes shiny-sparkle{0%,100%{opacity:0;transform:scale(0)}50%{opacity:1;transform:scale(1)}}
  .shiny-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.75);display:flex;align-items:center;justify-content:center;flex-direction:column;gap:clamp(12px,2vmin,24px);z-index:9999}
  .shiny-sprites{display:flex;gap:clamp(16px,3vmin,36px);align-items:center;justify-content:center}
  .shiny-sprite{width:clamp(80px,16vmin,160px);aspect-ratio:1;image-rendering:pixelated;animation:shiny-pop .6s ease-out both}
  .shiny-sprite img,.shiny-sprite .mon-sprite{width:100%;height:100%;object-fit:contain;image-rendering:pixelated}
  .shiny-text{font-family:var(--px);font-size:clamp(12px,3vmin,26px);-webkit-font-smoothing:none;color:var(--c-gold);text-shadow:0 0 30px var(--c-gold),0 0 60px rgba(248,208,48,.4);text-align:center;animation:shiny-pop .6s ease-out .1s both}
  .shiny-sub{font-size:.7em;opacity:.6;margin-top:.4em}
  .shiny-sparkle-wrap{position:absolute;inset:0;pointer-events:none;overflow:hidden}
  .shiny-sparkle{position:absolute;width:clamp(6px,1.2vmin,14px);aspect-ratio:1;border-radius:50%;background:var(--c-gold);animation:shiny-sparkle var(--dur,1.2s) ease-in-out var(--delay,0s) infinite}

  /* ─── Focus card overlay ──────────────────────────────────────────────── */
  .moves-grid{display:grid;grid-template-columns:1fr 1fr;gap:clamp(3px,.6vmin,7px);margin-top:clamp(4px,.7vmin,9px)}
  .move-tile{background:rgba(255,255,255,.05);border-radius:4px;padding:clamp(3px,.55vmin,7px);display:flex;flex-direction:column;gap:clamp(2px,.35vmin,4px);min-width:0}
  .move-name{font-family:var(--px);font-size:clamp(6px,1.1vmin,9px);-webkit-font-smoothing:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .pp-row{display:flex;align-items:center;gap:clamp(2px,.4vmin,5px);margin-top:clamp(1px,.2vmin,2px)}
  .pp-trk{flex:1;height:clamp(3px,.5vmin,5px);background:rgba(128,128,128,.18);border-radius:99px;overflow:hidden}
  .pp-fill{height:100%;border-radius:99px;transition:width .3s}
  .pp-h{background:var(--c-alive)}.pp-m{background:var(--c-gold)}.pp-l{background:var(--c-dead)}
  .pp-num{font-size:.72em;opacity:.55;flex-shrink:0;white-space:nowrap}
  .move-type{display:inline-block;font-family:var(--px);font-size:clamp(5px,.9vmin,7px);-webkit-font-smoothing:none;padding:1px 4px;border-radius:2px;color:#fff;letter-spacing:.04em;white-space:nowrap;align-self:flex-start;margin-top:clamp(1px,.2vmin,2px)}
  /* Gen 3 type colors by type_name */
  .mt-Normal{background:#a8a878;color:#fff}.mt-Fighting{background:#c03028}.mt-Flying{background:#a890f0}
  .mt-Poison{background:#a040a0}.mt-Ground{background:#e0c068;color:#111}.mt-Rock{background:#b8a038}
  .mt-Bug{background:#a8b820;color:#111}.mt-Ghost{background:#705898}.mt-Steel{background:#b8b8d0;color:#111}
  .mt-Fire{background:#f08030}.mt-Water{background:#6890f0}.mt-Grass{background:#78c850;color:#111}
  .mt-Electric{background:#f8d030;color:#111}.mt-Psychic{background:#f85888}.mt-Ice{background:#98d8d8;color:#111}
  .mt-Dragon{background:#7038f8}.mt-Dark{background:#705848}
  .mt-unknown,.mt-{background:#666}
  .focus-not-active{display:flex;flex:1;align-items:center;justify-content:center;opacity:.3;font-size:.85em;letter-spacing:.08em}

  /* ─── Encounters overlay ──────────────────────────────────────────────── */
  .enc-last{margin-top:clamp(5px,.9vmin,11px);display:flex;align-items:center;gap:clamp(4px,.8vmin,10px);padding:clamp(4px,.7vmin,8px) clamp(7px,1.1vmin,13px);background:var(--c-card);border-radius:4px;border-left:3px solid var(--c-gold);min-width:0}
  .enc-nms{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px}
  .enc-nm{font-size:.88em;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .enc-lv{font-size:.75em;opacity:.5;white-space:nowrap}
  .shiny-star{color:var(--c-gold);margin-left:3px}

"""

_STREAM_SHARED_JS = r"""
var spriteCache = {};
var _refreshInFlight = false;

function removeSpriteBackground(img) {
  if (img.dataset.bgRemoved || !img.naturalWidth) return;
  var src = img.src;
  if (src.indexOf('funnotbun') === -1) return;
  if (spriteCache[src]) { img.src = spriteCache[src]; img.dataset.bgRemoved='1'; return; }
  var c = document.createElement('canvas');
  c.width = img.naturalWidth; c.height = img.naturalHeight;
  var ctx = c.getContext('2d');
  ctx.drawImage(img, 0, 0);
  try {
    var data = ctx.getImageData(0, 0, c.width, c.height);
    var px = data.data;
    var bgR=px[0], bgG=px[1], bgB=px[2];
    for (var i=0; i<px.length; i+=4) {
      if (px[i]===bgR && px[i+1]===bgG && px[i+2]===bgB) px[i+3]=0;
    }
    ctx.putImageData(data, 0, 0);
    var dataUrl = c.toDataURL();
    spriteCache[src] = dataUrl;
    img.src = dataUrl;
  } catch(e) {}
  img.dataset.bgRemoved = '1';
}

function processSprites() {
  document.querySelectorAll('img.mon-sprite').forEach(function(img) {
    if (img.dataset.bgRemoved) return;
    if (img.complete && img.naturalWidth) removeSpriteBackground(img);
    else { img.crossOrigin='anonymous'; img.addEventListener('load', function(){removeSpriteBackground(img);}, {once:true}); }
  });
}

var badgeCache = {};
function trimBadge(img) {
  if (img.dataset.trimmed || !img.naturalWidth) return;
  var src = img.src;
  if (badgeCache[src]) { img.src = badgeCache[src]; img.dataset.trimmed='1'; return; }
  var w = img.naturalWidth, h = img.naturalHeight;
  if (w < 3 || h < 3) { img.dataset.trimmed='1'; return; }
  var c = document.createElement('canvas');
  c.width = w; c.height = h;
  var ctx = c.getContext('2d');
  try {
    ctx.drawImage(img, 0, 0);
    var data = ctx.getImageData(0, 0, w, h);
    var px = data.data;
    for (var y = 0; y < h; y++) {
      for (var x = 0; x < w; x++) {
        if (x === 0 || x === w-1 || y === 0 || y === h-1) {
          px[(y*w+x)*4+3] = 0;
        }
      }
    }
    ctx.putImageData(data, 0, 0);
    var dataUrl = c.toDataURL();
    badgeCache[src] = dataUrl;
    img.src = dataUrl;
  } catch(e) {}
  img.dataset.trimmed = '1';
}

function processBadges() {
  document.querySelectorAll('img.bdg-img').forEach(function(img) {
    if (img.dataset.trimmed) return;
    if (img.complete && img.naturalWidth) trimBadge(img);
    else { img.crossOrigin='anonymous'; img.addEventListener('load', function(){trimBadge(img);}, {once:true}); }
  });
}

function hpBar(hp, maxHP) {
  var pct = maxHP > 0 ? Math.max(0, Math.min(100, Math.round(hp/maxHP*100))) : 0;
  var cls = pct > 50 ? 'hp-high' : (pct > 20 ? 'hp-mid' : 'hp-low');
  return '<div class="hp-bar-bg"><div class="hp-bar '+cls+'" style="width:'+pct+'%"></div></div> <span class="dim">'+hp+'/'+maxHP+'</span>';
}

function spriteUrl(speciesId) {
  return 'https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/' + speciesId + '.png';
}

function spriteTag(speciesId) {
  if (!speciesId || speciesId < 1) return '';
  if (speciesId === 412) return '<img class="mon-sprite" src="https://play.pokemonshowdown.com/sprites/gen5/egg.png" onerror="this.style.display=\'none\';" alt="Egg">';
  var url = spriteUrl(speciesId);
  return '<img class="mon-sprite" crossorigin="anonymous" src="'+url+'" onerror="this.style.display=\'none\';" alt="">';
}

function monLabel(nick, speciesName, key) {
  if (nick && speciesName) return nick + ' <span class="dim">('+speciesName+')</span>';
  if (nick) return nick;
  if (speciesName) return speciesName;
  if (key) return key.substring(0, 8) + '…';
  return '—';
}

function statusIcon(cond) {
  if (!cond) return '';
  if (cond & 7)    return '<span class="sc sc-slp">SLP</span>';
  if (cond & 0x80) return '<span class="sc sc-tox">TOX</span>';
  if (cond & 0x08) return '<span class="sc sc-psn">PSN</span>';
  if (cond & 0x10) return '<span class="sc sc-brn">BRN</span>';
  if (cond & 0x20) return '<span class="sc sc-frz">FRZ</span>';
  if (cond & 0x40) return '<span class="sc sc-par">PAR</span>';
  return '';
}

var _STAT_LABELS = ['ATK','DEF','SPD','SATK','SDEF','ACC','EVA'];
function statStagesHtml(stages) {
  if (!Array.isArray(stages) || !stages.length) return '';
  var out = '';
  for (var i = 0; i < stages.length && i < _STAT_LABELS.length; i++) {
    var s = stages[i] - 6;
    if (!isFinite(s) || s === 0 || s < -6 || s > 6) continue;
    var sign  = s > 0 ? '+' : '\u2212';
    var cls   = s > 0 ? 'ss-up' : 'ss-dn';
    out += '<span class="stat-stage ' + cls + '">' + sign + Math.abs(s) + ' ' + _STAT_LABELS[i] + '</span>';
  }
  return out;
}

var _SPLIT_ICON_BASE = 'https://raw.githubusercontent.com/funnotbun/funnotbun.github.io/main/src/moves';
var _SPLIT_NAMES = ['SPLIT_PHYSICAL', 'SPLIT_SPECIAL', 'SPLIT_STATUS'];
var _SPLIT_CSS = ['split-physical', 'split-special', 'split-status'];
var _TYPE_COLORS = {Normal:'#A8A878',Fighting:'#C03028',Flying:'#A890F0',Poison:'#A040A0',Ground:'#E0C068',Rock:'#B8A038',Bug:'#A8B820',Ghost:'#705898',Steel:'#B8B8D0','???':'#68A090',Fire:'#F08030',Water:'#6890F0',Grass:'#78C850',Electric:'#F8D030',Psychic:'#F85888',Ice:'#98D8D8',Dragon:'#7038F8',Dark:'#705848',Fairy:'#EE99AC'};
var _LIGHT_TEXT_TYPES = {Electric:1,Ice:1,Normal:1,Ground:1,Fairy:1};

function moveTableHtml(moveDetails, isBox, monKey) {
  if (!moveDetails || moveDetails.length === 0) return '';
  var keyAttr = monKey ? ' data-mon-key="'+monKey+'"' : '';
  var rows = '';
  moveDetails.forEach(function(md) {
    var name = md.name || '?';
    var tn = md.type_name || '';
    var bg = _TYPE_COLORS[tn] || '#666';
    var tc = _LIGHT_TEXT_TYPES[tn] ? '#000' : '#fff';
    var splitIdx = md.split || 0;
    var splitImg = '<img class="split-icon '+(_SPLIT_CSS[splitIdx]||'')+'" src="'+_SPLIT_ICON_BASE+'/'+(_SPLIT_NAMES[splitIdx]||'SPLIT_PHYSICAL')+'.png" alt="">';
    var pwr = md.power > 0 ? md.power : '—';
    var acc = md.accuracy > 0 ? md.accuracy : '—';
    var pp;
    if (isBox) { pp = md.pp > 0 ? md.pp : '—'; }
    else { pp = md.pp > 0 ? (md.current_pp+'/'+md.pp) : '—'; }
    rows += '<tr><td class="mv-name">'+name+'</td>';
    rows += '<td><span class="type-badge" style="background:'+bg+';color:'+tc+'">'+tn+'</span></td>';
    rows += '<td>'+splitImg+'</td>';
    rows += '<td style="text-align:center">'+pwr+'</td>';
    rows += '<td style="text-align:center">'+acc+'</td>';
    rows += '<td>'+pp+'</td></tr>';
  });
  return '<details class="moves-details"'+keyAttr+'><summary>Moves ('+moveDetails.length+')</summary>'
    + '<table class="move-tbl"><thead><tr><th>Move</th><th>Type</th><th>Cat</th><th>Pwr</th><th>Acc</th><th>PP</th></tr></thead>'
    + '<tbody>'+rows+'</tbody></table></details>';
}

function doRefresh() {
  if (_refreshInFlight) return;
  _refreshInFlight = true;
  // Save open <details> state before re-render
  var openDetails = {};
  document.querySelectorAll('details.moves-details[open]').forEach(function(d) {
    var key = d.getAttribute('data-mon-key');
    if (key) openDetails[key] = true;
  });
  fetch('/api/status').then(function(r){return r.json();}).then(function(data) {
    _refreshInFlight = false;
    render(data);
    // Restore open <details> state after re-render
    Object.keys(openDetails).forEach(function(key) {
      var d = document.querySelector('details.moves-details[data-mon-key="'+key+'"]');
      if (d) d.setAttribute('open', '');
    });
    processSprites();
    autoFit();
  }).catch(function(){ _refreshInFlight = false; });
}

function autoFit() {
  var root = document.getElementById('root');
  if (!root) return;
  // Reset transform so we measure natural content height
  root.style.transform = '';
  root.style.transformOrigin = '';
  var sh = root.scrollHeight;
  var ch = root.clientHeight;
  if (sh > ch && ch > 0) {
    var scale = ch / sh;
    root.style.transformOrigin = 'top center';
    root.style.transform = 'scale(' + scale + ')';
  }
}

function init() {
  var params = new URLSearchParams(window.location.search);
  var theme = params.get('theme') || 'dark';
  var layout = params.get('layout') || '';
  var layoutCls = layout === 'h' ? ' lh' : layout === 'thin-h' ? ' lth' : layout === 'thin-v' ? ' ltv' : '';
  document.body.className = 'theme-' + theme + layoutCls;

  // Poll /api/status on a timer — no SSE connection.
  // Stream overlays intentionally avoid SSE to stay within Chrome's
  // 6-connections-per-origin limit (the main status page holds one SSE
  // connection; opening overlays in additional tabs would exhaust the pool
  // and cause all requests from that origin to queue indefinitely).
  doRefresh();
  setInterval(doRefresh, 2000);
}
window.addEventListener('DOMContentLoaded', init);
"""


def _stream_overlay_page(title: str, render_js: str) -> str:
    """Build a self-contained stream overlay HTML page.

    render_js must define a single ``render(data)`` function.  The shared
    polling loop (in _STREAM_SHARED_JS) calls render() every 2 seconds with
    the parsed /api/status JSON.

    DO NOT use EventSource or SSE inside render_js — see the section-level
    comment above _STREAM_SHARED_CSS for the full explanation.
    """
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} — Soul Link</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&display=swap" rel="stylesheet">
  <style>{_STREAM_SHARED_CSS}</style>
</head>
<body>
  <div id="root"></div>
  <script>{_STREAM_SHARED_JS}

{render_js}
  </script>
</body>
</html>"""


_STREAM_PARTY_JS = r"""
var PLAYER_ID = '%PLAYER%';
function escHtml(s){return s?s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'):''}
function render(d) {
  var p = d.players[PLAYER_ID];
  if (!p) { document.getElementById('root').innerHTML = '<div class="wtitle">PARTY \xb7 ' + PLAYER_ID.toUpperCase() + '</div><div style="opacity:.4;padding-top:6px">No data</div>'; return; }
  var name = escHtml(p.trainer_name || PLAYER_ID.toUpperCase());
  var keys = p.party_keys || [];
  var h = '<div class="wtitle">PARTY \xb7 ' + name + '</div>';
  h += '<div class="p-list">';
  if (!keys.length) {
    h += '<div style="opacity:.4;font-size:.9em">No party data</div>';
  } else {
    keys.forEach(function(key) {
      var det = (p.party_details && p.party_details[key]) || {};
      var hp = typeof det.hp === 'number' ? det.hp : 1;
      var maxHP = det.maxHP > 0 ? det.maxHP : (hp || 1);
      var lv = det.level || '?';
      var fnt = hp === 0;
      var pct = fnt ? 0 : Math.max(0, Math.min(100, Math.round(hp / maxHP * 100)));
      var hpCls = pct > 50 ? 'hp-h' : (pct > 20 ? 'hp-m' : 'hp-l');
      var bCls  = fnt ? 'fnt' : (pct > 50 ? 'bh' : (pct > 20 ? 'bm' : 'bl'));
      var nick  = escHtml(det.nickname || det.species_name || key.substring(0, 8));
      var spLbl = (det.species_name && det.nickname && det.nickname !== det.species_name)
                  ? ' <span class="sp">(' + escHtml(det.species_name) + ')</span>' : '';
      var fntTag = fnt ? '<span class="fnt-tag">FNT</span>' : '';
      h += '<div class="mc ' + bCls + '">';
      h += (det.sprite_html || spriteTag(det.species_id || 0));
      h += '<div class="m-info">';
      h += '<div class="m-name">' + nick + spLbl + fntTag + '</div>';
      h += '<div class="hp-row">';
      h += '<span class="hp-lbl">HP</span>';
      h += '<div class="hp-trk"><div class="hp-fill ' + hpCls + '" style="width:' + pct + '%"></div></div>';
      h += '<span class="hp-pct">' + (fnt ? '\u2014' : pct + '%') + '</span>';
      h += statusIcon(det.status_cond || 0);
      h += '<span class="lv">Lv ' + lv + '</span>';
      h += '</div>';
      if (det.active && det.stat_stages) {
        var stH = statStagesHtml(det.stat_stages);
        if (stH) h += '<div class="stat-stages-row">' + stH + '</div>';
      }
      h += '</div></div>';
    });
  }
  h += '</div>';
  document.getElementById('root').innerHTML = h;
}
"""

_STREAM_LINKS_JS = r"""
function escHtml(s){return s?s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'):''}
function areaLabel(id){
  if (!id) return '';
  if (id.indexOf('_bonus_') === 0) return '\u2736 Bonus Pair';
  return id.replace(/_/g,' ').replace(/\b\w/g,function(c){return c.toUpperCase();});
}
function render(d) {
  var links  = d.links || [];
  var alive  = links.filter(function(l){return l.status==='alive';});
  var dead   = links.filter(function(l){return l.status!=='alive';});
  var h = '<div class="wtitle">SOUL LINK \xb7 ' + alive.length + ' ALIVE \xb7 ' + dead.length + ' DEAD</div>';
  if (!links.length) {
    h += '<div style="opacity:.4;padding-top:.5em">No links yet</div>';
    document.getElementById('root').innerHTML = h; return;
  }
  h += '<div class="lk-list">';
  // ── Alive pairs — full card with area name and sprites ──────────────────
  alive.forEach(function(lnk) {
    var aN  = escHtml(lnk.a_nickname || lnk.a_species_name || '\u2014');
    var bN  = escHtml(lnk.b_nickname || lnk.b_species_name || '\u2014');
    var aL  = lnk.a_level ? 'Lv\u00a0' + lnk.a_level : '';
    var bL  = lnk.b_level ? 'Lv\u00a0' + lnk.b_level : '';
    var aSp = lnk.a_sprite_html || (lnk.a_species ? spriteTag(lnk.a_species) : '');
    var bSp = lnk.b_sprite_html || (lnk.b_species ? spriteTag(lnk.b_species) : '');
    var area = escHtml(lnk.area_display || areaLabel(lnk.area_id));
    h += '<div class="lk-card">';
    if (area) h += '<div class="lk-area">' + area + '</div>';
    h += '<div class="lk-pair">';
    h += '<div class="lk-half">' + aSp + '<span class="lk-nm">' + aN + '</span>';
    if (aL) h += '<span class="lk-lv">' + aL + '</span>';
    h += '</div>';
    h += '<span class="lk-div">\u25c8</span>';
    h += '<div class="lk-half r">';
    if (bL) h += '<span class="lk-lv">' + bL + '</span>';
    h += '<span class="lk-nm">' + bN + '</span>' + bSp;
    h += '</div></div></div>';
  });
  // ── Dead pairs — compact list, no sprites ───────────────────────────────
  if (dead.length) {
    h += '<div class="lk-dead-hdr">\u2015\u2015 ' + dead.length + ' DEAD \u2015\u2015</div>';
    dead.forEach(function(lnk) {
      var aN = escHtml(lnk.a_nickname || lnk.a_species_name || '\u2014');
      var bN = escHtml(lnk.b_nickname || lnk.b_species_name || '\u2014');
      h += '<div class="lk-dead-row">';
      h += '<span class="lk-dead-x">\u2717</span>';
      h += '<span class="lk-dead-nm">' + aN + '</span>';
      h += '<span class="lk-dead-sep">\u25c8</span>';
      h += '<span class="lk-dead-nm r">' + bN + '</span>';
      h += '</div>';
    });
  }
  h += '</div>';
  document.getElementById('root').innerHTML = h;
  processSprites();
}
"""

_STREAM_LINKED_PARTY_JS = r"""
function escHtml(s){return s?s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'):''}
function areaLabel(id){
  if (!id) return '';
  if (id.indexOf('_bonus_') === 0) return '\u2736 Bonus Pair';
  return id.replace(/_/g,' ').replace(/\b\w/g,function(c){return c.toUpperCase();});
}
function hpCls(pct){ return pct > 50 ? 'hp-h' : (pct > 20 ? 'hp-m' : 'hp-l'); }
function render(d) {
  var links = d.links || [];
  var pa = (d.players && d.players['a']) || {};
  var pb = (d.players && d.players['b']) || {};
  var aKeys = pa.party_keys || [];
  var bKeys = pb.party_keys || [];
  var pairs = links.filter(function(lnk) {
    return lnk.status === 'alive'
        && aKeys.indexOf(lnk.a_key) !== -1
        && bKeys.indexOf(lnk.b_key) !== -1;
  });
  var cnt = pairs.length;
  var h = '<div class="wtitle">LINKED PARTY</div>';
  if (!cnt) {
    h += '<div style="opacity:.4;padding-top:.5em;font-size:.9em">No linked pairs in party</div>';
    document.getElementById('root').innerHTML = h; return;
  }
  h += '<div class="lp-list">';
  pairs.forEach(function(lnk) {
    var aDet = (pa.party_details && pa.party_details[lnk.a_key]) || {};
    var bDet = (pb.party_details && pb.party_details[lnk.b_key]) || {};
    var aHp = typeof aDet.hp === 'number' ? aDet.hp : 1;
    var aMx = aDet.maxHP > 0 ? aDet.maxHP : (aHp || 1);
    var bHp = typeof bDet.hp === 'number' ? bDet.hp : 1;
    var bMx = bDet.maxHP > 0 ? bDet.maxHP : (bHp || 1);
    var aPct = aHp === 0 ? 0 : Math.max(0, Math.min(100, Math.round(aHp / aMx * 100)));
    var bPct = bHp === 0 ? 0 : Math.max(0, Math.min(100, Math.round(bHp / bMx * 100)));
    var aFnt = aHp === 0, bFnt = bHp === 0;
    var bothFnt = aFnt && bFnt;
    var aN  = escHtml(aDet.nickname || lnk.a_nickname || lnk.a_species_name || '\u2014');
    var bN  = escHtml(bDet.nickname || lnk.b_nickname || lnk.b_species_name || '\u2014');
    var aL  = aDet.level || lnk.a_level || '';
    var bL  = bDet.level || lnk.b_level || '';
    var aSp = aDet.sprite_html || lnk.a_sprite_html || (lnk.a_species ? spriteTag(lnk.a_species) : '');
    var bSp = bDet.sprite_html || lnk.b_sprite_html || (lnk.b_species ? spriteTag(lnk.b_species) : '');
    var area = escHtml(lnk.area_display || areaLabel(lnk.area_id));
    h += '<div class="lp-card' + (bothFnt ? ' ld' : '') + '">';
    if (area) h += '<div class="lp-area">' + area + '</div>';
    h += '<div class="lp-mons">';
    // Side A
    h += '<div class="lp-side' + (aFnt ? ' mc fnt' : '') + '">';
    h += aSp;
    h += '<div class="lp-info">';
    h += '<div class="lp-nm">' + aN + (aFnt ? '<span class="fnt-tag">FNT</span>' : '') + '</div>';
    h += '<div class="hp-row">';
    h += '<div class="hp-trk"><div class="hp-fill ' + hpCls(aPct) + '" style="width:' + aPct + '%"></div></div>';
    if (aL) h += '<span class="lv">Lv\u00a0' + aL + '</span>';
    h += '</div></div></div>';
    // Center
    h += '<span class="lp-sep">\u25c8</span>';
    // Side B (mirrored)
    h += '<div class="lp-side lp-r' + (bFnt ? ' mc fnt' : '') + '">';
    h += '<div class="lp-info lp-ir">';
    h += '<div class="lp-nm">' + (bFnt ? '<span class="fnt-tag">FNT</span>' : '') + bN + '</div>';
    h += '<div class="hp-row">';
    if (bL) h += '<span class="lv">Lv\u00a0' + bL + '</span>';
    h += '<div class="hp-trk"><div class="hp-fill ' + hpCls(bPct) + '" style="width:' + bPct + '%"></div></div>';
    h += '</div></div>';
    h += bSp;
    h += '</div>';
    h += '</div></div>';
  });
  h += '</div>';
  document.getElementById('root').innerHTML = h;
  processSprites();
}
"""

_STREAM_BOXED_LINKS_JS = r"""
function escHtml(s){return s?s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'):''}
function areaLabel(id){
  if (!id) return '';
  if (id.indexOf('_bonus_') === 0) return '\u2736 Bonus';
  return id.replace(/_/g,' ').replace(/\b\w/g,function(c){return c.toUpperCase();});
}
function render(d) {
  var links = d.links || [];
  var pa = (d.players && d.players['a']) || {};
  var pb = (d.players && d.players['b']) || {};
  var aKeys = pa.party_keys || [];
  var bKeys = pb.party_keys || [];
  /* Pairs where both are alive but at least one is NOT in party */
  var pairs = links.filter(function(lnk) {
    if (lnk.status !== 'alive') return false;
    var aIn = aKeys.indexOf(lnk.a_key) !== -1;
    var bIn = bKeys.indexOf(lnk.b_key) !== -1;
    return !(aIn && bIn);
  });
  var compact = pairs.length > 4;
  var h = '<div class="wtitle">BOXED LINKS \xb7 ' + pairs.length + '</div>';
  if (!pairs.length) {
    h += '<div style="opacity:.4;font-size:.9em;padding-top:.4em">All pairs in party</div>';
    document.getElementById('root').innerHTML = h; return;
  }
  if (compact) {
    /* Compact grid — sprites only with arrow */
    h += '<div class="bl-grid">';
    pairs.forEach(function(lnk) {
      var aSp = lnk.a_sprite_html || (lnk.a_species ? spriteTag(lnk.a_species) : '');
      var bSp = lnk.b_sprite_html || (lnk.b_species ? spriteTag(lnk.b_species) : '');
      h += '<div class="bl-gpair">';
      h += aSp;
      h += '<span class="bl-garr">\u25c8</span>';
      h += bSp;
      h += '</div>';
    });
    h += '</div>';
  } else {
    /* Detailed cards with names/levels */
    h += '<div class="bl-list">';
    pairs.forEach(function(lnk) {
    var aIn = aKeys.indexOf(lnk.a_key) !== -1;
    var bIn = bKeys.indexOf(lnk.b_key) !== -1;
    var aN = escHtml(lnk.a_nickname || lnk.a_species_name || '\u2014');
    var bN = escHtml(lnk.b_nickname || lnk.b_species_name || '\u2014');
    var aL = lnk.a_level ? 'Lv\u00a0' + lnk.a_level : '';
    var bL = lnk.b_level ? 'Lv\u00a0' + lnk.b_level : '';
    var aSp = lnk.a_sprite_html || (lnk.a_species ? spriteTag(lnk.a_species) : '');
    var bSp = lnk.b_sprite_html || (lnk.b_species ? spriteTag(lnk.b_species) : '');
    var area = escHtml(lnk.area_display || areaLabel(lnk.area_id));
    h += '<div class="bl-card">';
    if (area) h += '<div class="bl-area">' + area + '</div>';
    h += '<div class="bl-row">';
    /* Side A */
    h += '<div class="bl-side' + (!aIn ? ' bl-bx' : '') + '">';
    h += aSp;
    h += '<div class="bl-info"><div class="bl-nm">' + aN + '</div>';
    if (aL) h += '<div class="bl-lv">' + aL + '</div>';
    h += '</div></div>';
    h += '<span class="bl-sep">\u25c8</span>';
    /* Side B */
    h += '<div class="bl-side bl-r' + (!bIn ? ' bl-bx' : '') + '">';
    h += '<div class="bl-info bl-ir"><div class="bl-nm">' + bN + '</div>';
    if (bL) h += '<div class="bl-lv">' + bL + '</div>';
    h += '</div>';
    h += bSp;
    h += '</div>';
    h += '</div></div>';
  });
  h += '</div>';
  }
  document.getElementById('root').innerHTML = h;
  processSprites();
}
"""

_STREAM_DEATHS_JS = r"""
function render(d) {
  var links = d.links || [];
  var alive = 0, dead = 0;
  links.forEach(function(l) {
    if (l.status === 'alive') alive++;
    else if (l.status === 'dead' || l.status === 'memorial') dead++;
  });
  var h = '<div class="wtitle">SOUL LINK</div>';
  h += '<div class="d-wrap"><div class="d-grid">';
  h += '<div class="d-box d-alive"><span class="d-num">' + alive + '</span><span class="d-lbl">ALIVE</span></div>';
  h += '<div class="d-box d-dead"><span class="d-num">'  + dead  + '</span><span class="d-lbl">DEAD</span></div>';
  h += '</div></div>';
  document.getElementById('root').innerHTML = h;
}
"""

_STREAM_ATTEMPTS_JS = r"""
function render(d) {
  var count = d.attempts_count || 0;
  var h = '<div class="d-wrap"><div class="d-grid">';
  h += '<div class="d-box d-attempts"><span class="d-num">' + count + '</span><span class="d-lbl">ATTEMPTS</span></div>';
  h += '</div></div>';
  document.getElementById('root').innerHTML = h;
}
"""

_STREAM_AREAS_JS = r"""
function render(d) {
  var areas = d.area_states || {};
  var linked = 0, dead = 0, pend = 0;
  for (var a in areas) {
    var st = areas[a];
    if (st === 'linked') linked++;
    else if (st === 'dead_zone') dead++;
    else if (st === 'pending_a' || st === 'pending_b' || st === 'pending_both') pend++;
  }
  var h = '<div class="wtitle">AREAS</div>';
  h += '<div class="d-wrap"><div class="d-grid">';
  h += '<div class="d-box d-alive"><span class="d-num">' + linked + '</span><span class="d-lbl">LINKED</span></div>';
  h += '<div class="d-box d-dead"><span class="d-num">'  + dead   + '</span><span class="d-lbl">DEAD</span></div>';
  if (pend > 0) {
    h += '<div class="d-box a-pend"><span class="d-num">' + pend + '</span><span class="d-lbl">PENDING</span></div>';
  }
  h += '</div></div>';
  document.getElementById('root').innerHTML = h;
}
"""

_STREAM_EVENTS_JS = r"""
function escHtml(s){return s?s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'):''}
function render(d) {
  var events = d.recent_events || [];
  var nameA = escHtml((d.players.a && d.players.a.trainer_name) || 'A');
  var nameB = escHtml((d.players.b && d.players.b.trainer_name) || 'B');
  var typeMap = {capture:'ec',faint:'ef',whiteout:'ew',no_catch:'en',area_enter:'ea',
                 linked:'el',dead_zone:'ed',violation:'ev',key_change:'ek',force_faint:'ef',hello:'eh'};
  var h = '<div class="wtitle">EVENTS</div><div class="e-list">';
  if (!events.length) { h += '<div style="opacity:.4;font-size:.9em">No events yet</div>'; }
  events.slice(0, 16).forEach(function(ev) {
    var ts = '';
    if (ev.ts) {
      var dt = new Date(ev.ts);
      if (!isNaN(dt)) {
        var hh = dt.getHours() % 12 || 12;
        var mm = ('0' + dt.getMinutes()).slice(-2);
        ts = hh + ':' + mm + (dt.getHours() >= 12 ? 'p' : 'a');
      } else { ts = String(ev.ts).substring(11, 16); }
    }
    var who = ev.player === 'a' ? nameA : nameB;
    var cls = typeMap[ev.type] || '';
    h += '<div class="e-row">';
    h += '<span class="e-ts">'  + escHtml(ts) + '</span>';
    h += '<span class="e-who">' + who + '</span>';
    h += '<span class="e-msg ' + cls + '">' + escHtml(ev.text || ev.type || '') + '</span>';
    h += '</div>';
  });
  h += '</div>';
  document.getElementById('root').innerHTML = h;
}
"""

_STREAM_BADGES_JS = r"""
var _badgeStateKey = null;
var PLAYER = "%PLAYER%";

function render(data) {
  var slugs = data.badge_slugs || [];
  var p = data.players[PLAYER] || {};
  var stateKey = JSON.stringify(slugs) + '|'
    + (p.badges||0) + ',' + (p.kanto_badges||0) + ',' + (p.trainer_name||'');
  if (stateKey === _badgeStateKey) return;
  _badgeStateKey = stateKey;

  if (!slugs.length) {
    document.getElementById('root').innerHTML = '<span class="dim">No badge data</span>';
    return;
  }
  var BASE = 'https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/badges/';
  var primary = p.badges || 0;
  var kanto   = p.kanto_badges || 0;
  var name = p.trainer_name || ('Player ' + PLAYER.toUpperCase());
  var h = '<div class="wtitle">' + name + ' BADGES</div>';
  h += '<div class="bdg-wrap"><div class="bdg-player"><div class="bdg-strip">';
  slugs.forEach(function(pair, i) {
    var earned = i < 8 ? ((primary >> i) & 1) : ((kanto >> (i - 8)) & 1);
    h += '<img class="bdg-img ' + (earned ? 'on' : 'off') + '"'
          + ' crossorigin="anonymous"'
          + ' src="' + BASE + pair[0] + '.png"'
          + ' title="' + pair[1] + '" alt="' + pair[1] + '"'
          + ' onerror="this.style.display=\'none\';">';
  });
  h += '</div></div></div>';
  document.getElementById('root').innerHTML = h;
  processBadges();
}
"""

_STREAM_ENCOUNTERS_JS = r"""
function escHtml(s){return s?s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'):''}
function areaLabel(id){
  if (!id) return '';
  if (id.indexOf('_bonus_') === 0) return '\u2736 Bonus Pair';
  return id.replace(/_/g,' ').replace(/\b\w/g,function(c){return c.toUpperCase();});
}
var _encStateKey = null;
function render(d) {
  var links = d.links || [];
  var alive = links.filter(function(l){return l.status==='alive';}).length;
  var dead  = links.filter(function(l){return l.status!=='alive';}).length;
  var shinies = links.filter(function(l){return l.a_shiny||l.b_shiny;}).length;
  var bk = d.bonus_keys || {};
  var bKA = bk.a || []; var bKB = bk.b || [];
  shinies += bKA.length + bKB.length;
  var last = links.length > 0 ? links[links.length-1] : null;
  var lastA = last ? (last.a_species||0) : 0;
  var lastB = last ? (last.b_species||0) : 0;
  var stateKey = alive+','+dead+','+shinies+','+lastA+','+lastB;
  if (stateKey === _encStateKey) return;
  _encStateKey = stateKey;
  var h = '<div class="wtitle">ENCOUNTERS</div>';
  h += '<div class="d-wrap"><div class="d-grid">';
  h += '<div class="d-box d-alive"><span class="d-num">'+(alive+dead)+'</span><span class="d-lbl">LINKED</span></div>';
  h += '<div class="d-box d-dead"><span class="d-num">'+dead+'</span><span class="d-lbl">DEAD</span></div>';
  h += '<div class="d-box d-attempts"><span class="d-num">'+shinies+'</span><span class="d-lbl">SHINIES</span></div>';
  h += '</div></div>';
  if (last) {
    var aN = escHtml(last.a_nickname||last.a_species_name||'\u2014');
    var bN = escHtml(last.b_nickname||last.b_species_name||'\u2014');
    var aL = last.a_level ? 'Lv\u00a0'+last.a_level : '';
    var bL = last.b_level ? 'Lv\u00a0'+last.b_level : '';
    var aSp = last.a_sprite_html||(last.a_species?spriteTag(last.a_species):'');
    var bSp = last.b_sprite_html||(last.b_species?spriteTag(last.b_species):'');
    var aStar = last.a_shiny ? '<span class="shiny-star">\u2728</span>' : '';
    var bStar = last.b_shiny ? '<span class="shiny-star">\u2728</span>' : '';
    var area = escHtml(last.area_display||areaLabel(last.area_id));
    h += '<div class="wtitle" style="margin-top:clamp(5px,.9vmin,11px)">LAST ENCOUNTER'+(area?' \xb7 '+area:'')+'</div>';
    h += '<div class="enc-last">';
    h += aSp;
    h += '<div class="enc-nms"><div class="enc-nm">'+aN+aStar+'</div>';
    if(aL) h += '<div class="enc-lv">'+aL+'</div>';
    h += '</div>';
    h += '<span class="lk-div">\u25c8</span>';
    h += '<div class="enc-nms" style="text-align:right"><div class="enc-nm">'+bStar+bN+'</div>';
    if(bL) h += '<div class="enc-lv">'+bL+'</div>';
    h += '</div>';
    h += bSp;
    h += '</div>';
  }
  document.getElementById('root').innerHTML = h;
  processSprites();
}
"""

_STREAM_MEMORIAL_JS = r"""
function escHtml(s){return s?s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'):''}
function areaLabel(id){
  if (!id) return '';
  if (id.indexOf('_bonus_') === 0) return '\u2736 Bonus Pair';
  return id.replace(/_/g,' ').replace(/\b\w/g,function(c){return c.toUpperCase();});
}
var _memStateKey = null;
function render(d) {
  var kf = (d.killfeed || []).slice();
  kf.sort(function(a,b){return (a.killed_at||'').localeCompare(b.killed_at||'');});
  var stateKey = JSON.stringify(kf.map(function(k){return [k.killed_at,k.area_id,k.a_key,k.b_key];}));
  if (stateKey === _memStateKey) return;
  _memStateKey = stateKey;
  var h = '<div class="wtitle">IN MEMORIAM \xb7 '+kf.length+'</div>';
  if (!kf.length) {
    h += '<div style="opacity:.4;padding-top:.5em;font-size:.9em">No losses yet</div>';
    document.getElementById('root').innerHTML = h;
    return;
  }
  var listHtml = '';
  kf.forEach(function(k) {
    var aN = escHtml(k.a_nickname||k.a_species_name||'\u2014');
    var bN = escHtml(k.b_nickname||k.b_species_name||'\u2014');
    var aL = k.a_level ? 'Lv\u00a0'+k.a_level : '';
    var bL = k.b_level ? 'Lv\u00a0'+k.b_level : '';
    var aSp = k.a_sprite_html||(k.a_species?spriteTag(k.a_species):'');
    var bSp = k.b_sprite_html||(k.b_species?spriteTag(k.b_species):'');
    var area = escHtml(k.area_display||areaLabel(k.area_id));
    listHtml += '<div class="lk-row ld">';
    listHtml += aSp;
    listHtml += '<div class="lk-half"><span class="lk-nm">'+aN+'</span>';
    if(aL) listHtml += '<span class="lk-lv">'+aL+'</span>';
    listHtml += '</div>';
    listHtml += '<span class="lk-div">\u271D</span>';
    listHtml += '<div class="lk-half r">';
    if(bL) listHtml += '<span class="lk-lv">'+bL+'</span>';
    listHtml += '<span class="lk-nm">'+bN+'</span>';
    listHtml += '</div>';
    listHtml += bSp;
    if(area) listHtml += '<span style="font-size:.65em;opacity:.4;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:6em">'+area+'</span>';
    listHtml += '</div>';
  });
  var doubled = listHtml + listHtml;
  h += '<div class="mem-scroll-mask" id="mem-mask"><div class="lk-list" id="mem-list">'+doubled+'</div></div>';
  document.getElementById('root').innerHTML = h;
  processSprites();
  var mask = document.getElementById('mem-mask');
  var list = document.getElementById('mem-list');
  if (list && mask && list.scrollHeight > mask.clientHeight * 2) {
    var dur = Math.max(6, kf.length * 3);
    list.style.animation = 'memorial-scroll '+dur+'s linear infinite';
  }
}
"""

_STREAM_TICKER_JS = r"""
function escHtml(s){return s?s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'):''}
var _tickerStateKey = null;
function render(d) {
  var events = (d.recent_events || []).slice(0, 16);
  var nameA = escHtml((d.players.a && d.players.a.trainer_name) || 'A');
  var nameB = escHtml((d.players.b && d.players.b.trainer_name) || 'B');
  var typeMap = {capture:'ec',faint:'ef',whiteout:'ew',no_catch:'en',area_enter:'ea',
                 linked:'el',dead_zone:'ed',violation:'ev',key_change:'ek',force_faint:'ef',hello:'eh'};
  var stateKey = JSON.stringify(events.map(function(e){return [e.ts,e.type,e.text];}));
  if (stateKey === _tickerStateKey) return;
  _tickerStateKey = stateKey;
  var pills = '';
  events.forEach(function(ev) {
    var ts = '';
    if (ev.ts) {
      var dt = new Date(ev.ts);
      if (!isNaN(dt)) {
        var hh = dt.getHours() % 12 || 12;
        var mm = ('0' + dt.getMinutes()).slice(-2);
        ts = hh + ':' + mm + (dt.getHours() >= 12 ? 'p' : 'a');
      } else { ts = String(ev.ts).substring(11, 16); }
    }
    var who = ev.player === 'a' ? nameA : nameB;
    var cls = typeMap[ev.type] || '';
    pills += '<div class="t-pill">';
    pills += '<span class="e-ts">'+escHtml(ts)+'</span>';
    pills += '<span class="e-who">'+who+'</span>';
    pills += '<span class="e-msg '+cls+'">'+escHtml(ev.text||ev.type||'')+'</span>';
    pills += '</div>';
    pills += '<span style="opacity:.2;align-self:center;flex-shrink:0">\u25c8</span>';
  });
  var track = pills + pills;
  var h = '<div class="ticker-mask"><div class="ticker-track">'+track+'</div></div>';
  document.getElementById('root').innerHTML = h;
}
"""

_STREAM_FOCUS_JS = r"""
function escHtml(s){return s?s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'):''}
var _focusStateKey = null;
var PLAYER_ID = '%PLAYER%';
function render(d) {
  var p = d.players[PLAYER_ID] || {};
  var keys = p.party_keys || [];
  var activeKey = null, det = {};
  for (var i = 0; i < keys.length; i++) {
    var k = keys[i];
    var candidate = (p.party_details && p.party_details[k]) || {};
    if (candidate.active) { activeKey = k; det = candidate; break; }
  }
  var ppList = det.move_details ? det.move_details.map(function(m){return m.current_pp;}) : [];
  var stateKey = (activeKey||'')+'|'+(det.hp||0)+'|'+(det.status_cond||0)+'|'+JSON.stringify(det.stat_stages||[])+'|'+JSON.stringify(ppList);
  if (stateKey === _focusStateKey) return;
  _focusStateKey = stateKey;
  var root = document.getElementById('root');
  var name = escHtml(p.trainer_name || PLAYER_ID.toUpperCase());
  if (!activeKey) {
    root.innerHTML = '<div class="wtitle">FOCUS \xb7 '+name+'</div><div class="focus-not-active">NOT IN BATTLE</div>';
    return;
  }
  var hp = typeof det.hp === 'number' ? det.hp : 1;
  var maxHP = det.maxHP > 0 ? det.maxHP : (hp || 1);
  var lv = det.level || '?';
  var fnt = hp === 0;
  var pct = fnt ? 0 : Math.max(0, Math.min(100, Math.round(hp/maxHP*100)));
  var hpCls = pct > 50 ? 'hp-h' : (pct > 20 ? 'hp-m' : 'hp-l');
  var bCls  = fnt ? 'fnt' : (pct > 50 ? 'bh' : (pct > 20 ? 'bm' : 'bl'));
  var nick  = escHtml(det.nickname || det.species_name || activeKey.substring(0,8));
  var spLbl = (det.species_name && det.nickname && det.nickname !== det.species_name)
              ? ' <span class="sp">('+escHtml(det.species_name)+')</span>' : '';
  var h = '<div class="wtitle">FOCUS \xb7 '+name+'</div>';
  h += '<div class="mc '+bCls+'">';
  h += (det.sprite_html || spriteTag(det.species_id||0));
  h += '<div class="m-info">';
  h += '<div class="m-name">'+nick+spLbl+'</div>';
  h += '<div class="hp-row">';
  h += '<span class="hp-lbl">HP</span>';
  h += '<div class="hp-trk"><div class="hp-fill '+hpCls+'" style="width:'+pct+'%"></div></div>';
  h += '<span class="hp-pct">'+(fnt?'\u2014':pct+'%')+'</span>';
  h += statusIcon(det.status_cond||0);
  h += '<span class="lv">Lv '+lv+'</span>';
  h += '</div>';
  if (det.stat_stages) {
    var stH = statStagesHtml(det.stat_stages);
    if (stH) h += '<div class="stat-stages-row">'+stH+'</div>';
  }
  h += '</div></div>';
  var moves = det.move_details || [];
  if (moves.length) {
    h += '<div class="moves-grid">';
    for (var mi = 0; mi < 4; mi++) {
      var md = moves[mi] || null;
      h += '<div class="move-tile">';
      if (md) {
        var mn = escHtml(md.name || '?');
        var tn = escHtml(md.type_name || '');
        var pp = md.pp > 0 ? md.current_pp : 0;
        var ppMax = md.pp || 1;
        var ppPct = Math.max(0, Math.min(100, Math.round(pp/ppMax*100)));
        var ppCls = ppPct > 50 ? 'pp-h' : (ppPct > 25 ? 'pp-m' : 'pp-l');
        var tc = 'mt-'+(tn||'unknown');
        h += '<div class="move-name">'+mn+'</div>';
        h += '<span class="move-type '+tc+'">'+tn+'</span>';
        h += '<div class="pp-row">';
        h += '<div class="pp-trk"><div class="pp-fill '+ppCls+'" style="width:'+ppPct+'%"></div></div>';
        h += '<span class="pp-num">'+pp+'/'+ppMax+'</span>';
        h += '</div>';
      } else {
        h += '<div class="move-name" style="opacity:.25">\u2014</div>';
      }
      h += '</div>';
    }
    h += '</div>';
  }
  root.innerHTML = h;
  processSprites();
}
"""

_STREAM_SHINY_ALERT_JS = r"""
function escHtml(s){return s?s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'):''}
var _seenShinies = null;
var _shinyStateKey = null;
function _getAllShinies(d) {
  var seen = {};
  (d.links || []).forEach(function(l) {
    if (l.a_shiny && l.a_key) seen[l.a_key] = l;
    if (l.b_shiny && l.b_key) seen[l.b_key] = l;
  });
  var bk = d.bonus_keys || {};
  (bk.a || []).forEach(function(k){ if (!seen[k]) seen[k] = {a_key:k,a_shiny:true,a_species:0}; });
  (bk.b || []).forEach(function(k){ if (!seen[k]) seen[k] = {b_key:k,b_shiny:true,b_species:0}; });
  return seen;
}
function _fireAlert(shinySide) {
  var wrap = document.createElement('div');
  wrap.className = 'shiny-backdrop';
  wrap.id = 'shiny-alert-wrap';
  var sparkleWrap = document.createElement('div');
  sparkleWrap.className = 'shiny-sparkle-wrap';
  for (var i = 0; i < 18; i++) {
    var sp = document.createElement('div');
    sp.className = 'shiny-sparkle';
    sp.style.cssText = 'left:'+Math.random()*100+'%;top:'+Math.random()*100+'%;'
      +'--dur:'+(0.8+Math.random()*1.2)+'s;--delay:'+(Math.random()*1.5)+'s';
    sparkleWrap.appendChild(sp);
  }
  wrap.appendChild(sparkleWrap);
  var txt = document.createElement('div');
  txt.className = 'shiny-text';
  txt.innerHTML = '\u2728 SHINY ENCOUNTER \u2728<div class="shiny-sub">'
    + escHtml(shinySide.nickname||shinySide.species_name||'') + '</div>';
  var sprites = document.createElement('div');
  sprites.className = 'shiny-sprites';
  var spA = shinySide.sprite_html || (shinySide.species_id ? '<img class="shiny-sprite" crossorigin="anonymous" src="https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/shiny/'+shinySide.species_id+'.png" onerror="this.src=\'https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/'+shinySide.species_id+'.png\'" alt="">' : '');
  if (spA) {
    var imgEl = document.createElement('div');
    imgEl.className = 'shiny-sprite';
    imgEl.innerHTML = spA;
    sprites.appendChild(imgEl);
  }
  if (shinySide.partner_sprite_html || shinySide.partner_species_id) {
    var pSp = shinySide.partner_sprite_html || '<img class="shiny-sprite" crossorigin="anonymous" src="https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/'+shinySide.partner_species_id+'.png" alt="">';
    var pEl = document.createElement('div');
    pEl.className = 'shiny-sprite';
    pEl.innerHTML = pSp;
    sprites.appendChild(pEl);
  }
  wrap.appendChild(sprites);
  wrap.appendChild(txt);
  document.body.appendChild(wrap);
  processSprites();
  function cleanup() {
    if (wrap.parentNode) wrap.parentNode.removeChild(wrap);
  }
  setTimeout(cleanup, 7000);
}
function render(d) {
  document.getElementById('root').innerHTML = '';
  var current = _getAllShinies(d);
  var currentKeys = Object.keys(current).sort();
  var stateKey = currentKeys.join('|');
  if (stateKey === _shinyStateKey) return;
  _shinyStateKey = stateKey;
  if (_seenShinies === null) {
    _seenShinies = {};
    currentKeys.forEach(function(k){ _seenShinies[k] = true; });
    return;
  }
  currentKeys.forEach(function(k) {
    if (_seenShinies[k]) return;
    _seenShinies[k] = true;
    if (document.getElementById('shiny-alert-wrap')) return;
    var entry = current[k];
    var isA = entry.a_key === k;
    var sid = isA ? (entry.a_species||0) : (entry.b_species||0);
    var nick = isA ? (entry.a_nickname||entry.a_species_name||'') : (entry.b_nickname||entry.b_species_name||'');
    var spHtml = isA ? (entry.a_sprite_html||'') : (entry.b_sprite_html||'');
    var pSid = isA ? (entry.b_species||0) : (entry.a_species||0);
    var pSpHtml = isA ? (entry.b_sprite_html||'') : (entry.a_sprite_html||'');
    _fireAlert({sprite_html:spHtml, species_id:sid, nickname:nick, species_name:nick, partner_sprite_html:pSpHtml, partner_species_id:pSid});
  });
}
"""

_STREAM_INDEX_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Soul Link Stream Overlays</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&display=swap" rel="stylesheet">
  <style>
    body { font-family: system-ui,'Segoe UI',sans-serif; background: #0a0c14; color: #e0e0e0; padding: 1.5em; margin: 0; }
    h1 { font-family: 'Press Start 2P','Courier New',monospace; color: #f8d030; margin-bottom: 0.4em; font-size: 1.1em; letter-spacing: .04em; }
    p.sub { color: #888; margin-bottom: 1.5em; font-size: .88em; }
    .obs-tip { background: rgba(248,208,48,.08); border: 1px solid rgba(248,208,48,.25); border-radius: 6px; padding: 10px 14px; margin-bottom: 1.5em; font-size: .83em; color: #bba; }
    .obs-tip b { color: #f8d030; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 1.2em; }
    .overlay-card { background: #12141e; border: 1px solid #2a2c3a; border-top: 2px solid #2a2c3a; border-radius: 8px; overflow: hidden; transition: border-color .2s; }
    .overlay-card:hover { border-color: #6af; border-top-color: #f8d030; }
    .preview { width: 100%; height: 180px; background: repeating-conic-gradient(#1a1c26 0% 25%, #141620 0% 50%) 50%/16px 16px; border-bottom: 1px solid #2a2c3a; }
    .preview iframe { width: 100%; height: 100%; border: none; pointer-events: none; }
    .overlay-info { padding: 12px 14px; }
    .overlay-info h3 { color: #eee; margin: 0 0 2px 0; font-size: .95em; }
    .size-hint { font-family: 'Press Start 2P','Courier New',monospace; font-size: .6em; color: #f8d030; opacity: .7; margin-bottom: 6px; }
    .overlay-info p { color: #888; font-size: .83em; margin: 0 0 8px 0; }
    .url-row { display: flex; gap: 6px; align-items: center; }
    .url-box { flex: 1; background: #1a1c28; color: #6af; border: 1px solid #363850; border-radius: 4px; padding: 4px 8px; font-family: monospace; font-size: .82em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .copy-btn { background: #1a2a3a; color: #6af; border: 1px solid #6af; border-radius: 4px; padding: 4px 10px; cursor: pointer; font-size: 0.82em; white-space: nowrap; }
    .copy-btn:hover { background: #2a3a4a; }
    .theme-toggle { margin-top: 8px; display: flex; gap: 6px; }
    .theme-toggle a { color: #aaa; font-size: 0.8em; text-decoration: none; padding: 2px 8px; border: 1px solid #444; border-radius: 3px; }
    .theme-toggle a:hover { color: #fff; border-color: #666; }
  </style>
</head>
<body>
  <h1>&#9670; Soul Link Overlays</h1>
  <p class="sub">OBS Browser Source-ready overlays — designed for Soul Link Nuzlocke streams.</p>
  <div class="obs-tip"><b>OBS setup:</b> Add a Browser Source &rarr; paste the URL &rarr; set width/height per the recommended size. The default Browser Source Custom CSS already handles transparent backgrounds &mdash; no extra settings needed.</div>
  <div class="grid">
    <div class="overlay-card">
      <div class="preview"><iframe src="/stream/party-a?theme=dark"></iframe></div>
      <div class="overlay-info">
        <h3>Player A Party</h3>
        <div class="size-hint">Vertical: 280 &times; 380 &nbsp;|&nbsp; Horizontal: 580 &times; 130 &nbsp;|&nbsp; Strip: 1200 &times; 150</div>
        <p>Sprites, HP bars, and levels. Designed for a tall side panel alongside the game.</p>
        <div class="url-row"><span class="url-box" id="u1">/stream/party-a</span><button class="copy-btn" onclick="copyUrl('u1')">Copy</button></div>
        <div class="theme-toggle"><a href="/stream/party-a?theme=dark" target="_blank">Dark</a><a href="/stream/party-a?theme=light" target="_blank">Light</a><a href="/stream/party-a?theme=transparent" target="_blank">Transparent</a><a href="/stream/party-a?layout=h&theme=dark" target="_blank">Horizontal</a><a href="/stream/party-a?layout=thin-h&theme=dark" target="_blank">Thin strip</a><a href="/stream/party-a?layout=thin-v&theme=dark" target="_blank">Thin sidebar</a></div>
      </div>
    </div>
    <div class="overlay-card">
      <div class="preview"><iframe src="/stream/party-b?theme=dark"></iframe></div>
      <div class="overlay-info">
        <h3>Player B Party</h3>
        <div class="size-hint">Vertical: 280 &times; 380 &nbsp;|&nbsp; Horizontal: 580 &times; 130 &nbsp;|&nbsp; Strip: 1200 &times; 150</div>
        <p>Sprites, HP bars, and levels. Designed for a tall side panel alongside the game.</p>
        <div class="url-row"><span class="url-box" id="u2">/stream/party-b</span><button class="copy-btn" onclick="copyUrl('u2')">Copy</button></div>
        <div class="theme-toggle"><a href="/stream/party-b?theme=dark" target="_blank">Dark</a><a href="/stream/party-b?theme=light" target="_blank">Light</a><a href="/stream/party-b?theme=transparent" target="_blank">Transparent</a><a href="/stream/party-b?layout=h&theme=dark" target="_blank">Horizontal</a><a href="/stream/party-b?layout=thin-h&theme=dark" target="_blank">Thin strip</a><a href="/stream/party-b?layout=thin-v&theme=dark" target="_blank">Thin sidebar</a></div>
      </div>
    </div>
    <div class="overlay-card">
      <div class="preview"><iframe src="/stream/links?theme=dark"></iframe></div>
      <div class="overlay-info">
        <h3>Linked Pairs</h3>
        <div class="size-hint">Vertical: 420 &times; 340 &nbsp;|&nbsp; Horizontal: 900 &times; 200 &nbsp;|&nbsp; Strip: 1400 &times; 180</div>
        <p>Alive pairs as full cards (area name + sprites). Dead pairs as a compact dimmed list below.</p>
        <div class="url-row"><span class="url-box" id="u3">/stream/links</span><button class="copy-btn" onclick="copyUrl('u3')">Copy</button></div>
        <div class="theme-toggle"><a href="/stream/links?theme=dark" target="_blank">Dark</a><a href="/stream/links?theme=light" target="_blank">Light</a><a href="/stream/links?theme=transparent" target="_blank">Transparent</a><a href="/stream/links?layout=h&theme=dark" target="_blank">Horizontal</a><a href="/stream/links?layout=thin-h&theme=dark" target="_blank">Thin strip</a><a href="/stream/links?layout=thin-v&theme=dark" target="_blank">Thin sidebar</a></div>
      </div>
    </div>
    <div class="overlay-card">
      <div class="preview"><iframe src="/stream/linked-party?theme=dark"></iframe></div>
      <div class="overlay-info">
        <h3>Linked Party ★</h3>
        <div class="size-hint">Standard: 500 &times; 320 &nbsp;|&nbsp; Bottom strip: 1400 &times; 150 &nbsp;|&nbsp; Sidebar: 160 &times; 500</div>
        <p>Shows only linked pairs where <b>both mons are currently in party</b> &mdash; HP bars, levels, area. The primary overlay for active streaming.</p>
        <div class="url-row"><span class="url-box" id="u3b">/stream/linked-party</span><button class="copy-btn" onclick="copyUrl('u3b')">Copy</button></div>
        <div class="theme-toggle"><a href="/stream/linked-party?theme=dark" target="_blank">Dark</a><a href="/stream/linked-party?theme=light" target="_blank">Light</a><a href="/stream/linked-party?theme=transparent" target="_blank">Transparent</a><a href="/stream/linked-party?layout=thin-h&theme=dark" target="_blank">Thin strip</a><a href="/stream/linked-party?layout=thin-v&theme=dark" target="_blank">Thin sidebar</a></div>
      </div>
    </div>
    <div class="overlay-card">
      <div class="preview"><iframe src="/stream/boxed-links?theme=dark"></iframe></div>
      <div class="overlay-info">
        <h3>Boxed Links</h3>
        <div class="size-hint">Sidebar: 200 &times; 600 &nbsp;|&nbsp; Standard: 420 &times; 340</div>
        <p>Alive linked pairs where one or both mons are currently in the PC box.</p>
        <div class="url-row"><span class="url-box" id="u3c">/stream/boxed-links</span><button class="copy-btn" onclick="copyUrl('u3c')">Copy</button></div>
        <div class="theme-toggle"><a href="/stream/boxed-links?theme=dark" target="_blank">Dark</a><a href="/stream/boxed-links?theme=light" target="_blank">Light</a><a href="/stream/boxed-links?theme=transparent" target="_blank">Transparent</a><a href="/stream/boxed-links?layout=thin-v&theme=dark" target="_blank">Thin sidebar</a></div>
      </div>
    </div>
    <div class="overlay-card">
      <div class="preview"><iframe src="/stream/deaths?theme=dark"></iframe></div>
      <div class="overlay-info">
        <h3>Death Counter</h3>
        <div class="size-hint">Recommended: 280 &times; 160</div>
        <p>Alive / dead pair counts with glow. Scales to any size &mdash; great for a corner badge.</p>
        <div class="url-row"><span class="url-box" id="u4">/stream/deaths</span><button class="copy-btn" onclick="copyUrl('u4')">Copy</button></div>
        <div class="theme-toggle"><a href="/stream/deaths?theme=dark" target="_blank">Dark</a><a href="/stream/deaths?theme=light" target="_blank">Light</a><a href="/stream/deaths?theme=transparent" target="_blank">Transparent</a></div>
      </div>
    </div>
    <div class="overlay-card">
      <div class="preview"><iframe src="/stream/attempts?theme=dark"></iframe></div>
      <div class="overlay-info">
        <h3>Attempts Counter</h3>
        <div class="size-hint">Recommended: 200 &times; 160</div>
        <p>Manual run attempt counter with glow. Set the number below or via the API.</p>
        <div class="url-row"><span class="url-box" id="u4b">/stream/attempts</span><button class="copy-btn" onclick="copyUrl('u4b')">Copy</button></div>
        <div class="theme-toggle"><a href="/stream/attempts?theme=dark" target="_blank">Dark</a><a href="/stream/attempts?theme=light" target="_blank">Light</a><a href="/stream/attempts?theme=transparent" target="_blank">Transparent</a></div>
        <div style="margin-top:8px;display:flex;gap:6px;align-items:center">
          <input type="number" id="attempts-input" min="0" value="0" style="width:60px;background:#1a1c28;color:#f8d030;border:1px solid #363850;border-radius:4px;padding:4px 8px;font-family:'Press Start 2P',monospace;font-size:.7em;text-align:center">
          <button class="copy-btn" onclick="setAttempts()">Set</button>
        </div>
      </div>
    </div>
    <div class="overlay-card">
      <div class="preview"><iframe src="/stream/areas?theme=dark"></iframe></div>
      <div class="overlay-info">
        <h3>Area Tracker</h3>
        <div class="size-hint">Vertical: 220 &times; 160 &nbsp;|&nbsp; Horizontal: 380 &times; 80</div>
        <p>Linked / dead zone / pending area counts at a glance.</p>
        <div class="url-row"><span class="url-box" id="u5">/stream/areas</span><button class="copy-btn" onclick="copyUrl('u5')">Copy</button></div>
        <div class="theme-toggle"><a href="/stream/areas?theme=dark" target="_blank">Dark</a><a href="/stream/areas?theme=light" target="_blank">Light</a><a href="/stream/areas?theme=transparent" target="_blank">Transparent</a><a href="/stream/areas?layout=h&theme=dark" target="_blank">Horizontal</a></div>
      </div>
    </div>
    <div class="overlay-card">
      <div class="preview"><iframe src="/stream/events?theme=dark"></iframe></div>
      <div class="overlay-info">
        <h3>Event Feed</h3>
        <div class="size-hint">Recommended: 400 &times; 280</div>
        <p>Live feed of captures, faints, area entries, and soul link events.</p>
        <div class="url-row"><span class="url-box" id="u6">/stream/events</span><button class="copy-btn" onclick="copyUrl('u6')">Copy</button></div>
        <div class="theme-toggle"><a href="/stream/events?theme=dark" target="_blank">Dark</a><a href="/stream/events?theme=light" target="_blank">Light</a><a href="/stream/events?theme=transparent" target="_blank">Transparent</a></div>
      </div>
    </div>
    <div class="overlay-card">
      <div class="preview"><iframe src="/stream/badges-a?theme=dark"></iframe></div>
      <div class="overlay-info">
        <h3>Gym Badges — Player A</h3>
        <div class="size-hint">Recommended: 340 &times; 80</div>
        <p>Player A's earned gym badges. Unearned badges are dimmed.</p>
        <div class="url-row"><span class="url-box" id="u7">/stream/badges-a</span><button class="copy-btn" onclick="copyUrl('u7')">Copy</button></div>
        <div class="theme-toggle"><a href="/stream/badges-a?theme=dark" target="_blank">Dark</a><a href="/stream/badges-a?theme=light" target="_blank">Light</a><a href="/stream/badges-a?theme=transparent" target="_blank">Transparent</a></div>
      </div>
    </div>
    <div class="overlay-card">
      <div class="preview"><iframe src="/stream/badges-b?theme=dark"></iframe></div>
      <div class="overlay-info">
        <h3>Gym Badges — Player B</h3>
        <div class="size-hint">Recommended: 340 &times; 80</div>
        <p>Player B's earned gym badges. Unearned badges are dimmed.</p>
        <div class="url-row"><span class="url-box" id="u8">/stream/badges-b</span><button class="copy-btn" onclick="copyUrl('u8')">Copy</button></div>
        <div class="theme-toggle"><a href="/stream/badges-b?theme=dark" target="_blank">Dark</a><a href="/stream/badges-b?theme=light" target="_blank">Light</a><a href="/stream/badges-b?theme=transparent" target="_blank">Transparent</a></div>
      </div>
    </div>
    <div class="overlay-card">
      <div class="preview"><iframe src="/stream/encounters?theme=dark"></iframe></div>
      <div class="overlay-info">
        <h3>Encounter Tracker</h3>
        <div class="size-hint">Standard: 340 &times; 200 &nbsp;|&nbsp; Wide: 560 &times; 120</div>
        <p>Total encounters, shiny count, and last linked encounter pair.</p>
        <div class="url-row"><span class="url-box" id="ue1">/stream/encounters</span><button class="copy-btn" onclick="copyUrl('ue1')">Copy</button></div>
        <div class="theme-toggle"><a href="/stream/encounters?theme=dark" target="_blank">Dark</a><a href="/stream/encounters?theme=light" target="_blank">Light</a><a href="/stream/encounters?theme=transparent" target="_blank">Transparent</a></div>
      </div>
    </div>
    <div class="overlay-card">
      <div class="preview"><iframe src="/stream/stream-memorial?theme=dark"></iframe></div>
      <div class="overlay-info">
        <h3>Memorial Scroll</h3>
        <div class="size-hint">Sidebar: 320 &times; 600</div>
        <p>Chronological scrolling list of all dead pairs with sprites. Auto-scrolls when content exceeds height.</p>
        <div class="url-row"><span class="url-box" id="um1">/stream/stream-memorial</span><button class="copy-btn" onclick="copyUrl('um1')">Copy</button></div>
        <div class="theme-toggle"><a href="/stream/stream-memorial?theme=dark" target="_blank">Dark</a><a href="/stream/stream-memorial?theme=light" target="_blank">Light</a><a href="/stream/stream-memorial?theme=transparent" target="_blank">Transparent</a></div>
      </div>
    </div>
    <div class="overlay-card">
      <div class="preview"><iframe src="/stream/ticker?theme=dark"></iframe></div>
      <div class="overlay-info">
        <h3>Event Ticker</h3>
        <div class="size-hint">Bottom strip: 1920 &times; 60</div>
        <p>Horizontally scrolling marquee of recent events. Place at the bottom of the stream.</p>
        <div class="url-row"><span class="url-box" id="ut1">/stream/ticker</span><button class="copy-btn" onclick="copyUrl('ut1')">Copy</button></div>
        <div class="theme-toggle"><a href="/stream/ticker?theme=dark" target="_blank">Dark</a><a href="/stream/ticker?theme=light" target="_blank">Light</a><a href="/stream/ticker?theme=transparent" target="_blank">Transparent</a></div>
      </div>
    </div>
    <div class="overlay-card">
      <div class="preview"><iframe src="/stream/focus-a?theme=dark"></iframe></div>
      <div class="overlay-info">
        <h3>Focus Card — Player A</h3>
        <div class="size-hint">Recommended: 340 &times; 380</div>
        <p>Active battle mon hero card: sprite, HP, status, stat stages, and 4-move grid with PP bars.</p>
        <div class="url-row"><span class="url-box" id="uf1">/stream/focus-a</span><button class="copy-btn" onclick="copyUrl('uf1')">Copy</button></div>
        <div class="theme-toggle"><a href="/stream/focus-a?theme=dark" target="_blank">Dark</a><a href="/stream/focus-a?theme=light" target="_blank">Light</a><a href="/stream/focus-a?theme=transparent" target="_blank">Transparent</a></div>
      </div>
    </div>
    <div class="overlay-card">
      <div class="preview"><iframe src="/stream/focus-b?theme=dark"></iframe></div>
      <div class="overlay-info">
        <h3>Focus Card — Player B</h3>
        <div class="size-hint">Recommended: 340 &times; 380</div>
        <p>Active battle mon hero card: sprite, HP, status, stat stages, and 4-move grid with PP bars.</p>
        <div class="url-row"><span class="url-box" id="uf2">/stream/focus-b</span><button class="copy-btn" onclick="copyUrl('uf2')">Copy</button></div>
        <div class="theme-toggle"><a href="/stream/focus-b?theme=dark" target="_blank">Dark</a><a href="/stream/focus-b?theme=light" target="_blank">Light</a><a href="/stream/focus-b?theme=transparent" target="_blank">Transparent</a></div>
      </div>
    </div>
    <div class="overlay-card">
      <div class="preview" style="background:#000"><iframe src="/stream/shiny-alert?theme=transparent"></iframe></div>
      <div class="overlay-info">
        <h3>Shiny Alert &#10024;</h3>
        <div class="size-hint">Full canvas: 1920 &times; 1080 &mdash; use transparent theme</div>
        <p>Full-screen celebration animation when a shiny is encountered. Add above all other sources. Normally invisible.</p>
        <div class="url-row"><span class="url-box" id="us1">/stream/shiny-alert</span><button class="copy-btn" onclick="copyUrl('us1')">Copy</button></div>
        <div class="theme-toggle"><a href="/stream/shiny-alert?theme=transparent" target="_blank">Transparent (recommended)</a><a href="/stream/shiny-alert?theme=dark" target="_blank">Dark</a></div>
      </div>
    </div>
  </div>
  <script>
    function copyUrl(id) {
      var el = document.getElementById(id);
      var url = window.location.origin + el.textContent;
      navigator.clipboard.writeText(url).then(function() {
        el.style.color = '#4f4';
        setTimeout(function(){el.style.color='';}, 1500);
      });
    }
    function setAttempts() {
      var inp = document.getElementById('attempts-input');
      var val = parseInt(inp.value, 10);
      if (isNaN(val) || val < 0) return;
      fetch('/api/attempts', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({count:val})})
        .then(function(r){return r.json();})
        .then(function(j){ if(j.ok) { inp.style.borderColor='#4f4'; setTimeout(function(){inp.style.borderColor='';},1500); }});
    }
    // Load current attempts count on page load
    fetch('/api/status').then(function(r){return r.json();}).then(function(d){
      var inp = document.getElementById('attempts-input');
      if (inp && typeof d.attempts_count === 'number') inp.value = d.attempts_count;
    });
  </script>
</body>
</html>"""


# ── Memorial Wall page ─────────────────────────────────────────────────────────

_MEMORIAL_HTML = r"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Memorial Wall — {page_title}</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0a0a0c; color: #ccc; padding: 2em; min-height: 100vh; }
    h1 { text-align: center; color: #888; font-weight: 300; font-size: 1.8em; letter-spacing: 0.15em;
         margin-bottom: 0.2em; }
    h1 span { color: #f44; }
    .subtitle { text-align: center; color: #555; font-size: 0.9em; margin-bottom: 2em; }
    .subtitle a { color: #6af; text-decoration: none; }
    .subtitle a:hover { text-decoration: underline; }
    .empty-msg { text-align: center; color: #555; font-size: 1.1em; margin-top: 4em;
                 font-style: italic; }
    .count { text-align: center; color: #666; font-size: 0.85em; margin-bottom: 1.5em; }

    .wall { display: flex; flex-wrap: wrap; gap: 1.2em; justify-content: center; }
    .tomb { background: #12121a; border: 1px solid #2a2a35; border-radius: 10px;
            width: 300px; padding: 1.2em 1em 1em; position: relative;
            transition: border-color 0.3s; }
    .tomb:hover { border-color: #444; }
    .tomb-header { display: flex; align-items: center; gap: 0.3em; justify-content: center;
                   margin-bottom: 0.5em; }
    .tomb-area { color: #7cf; font-size: 0.82em; text-align: center; margin-bottom: 0.8em; }
    .tomb-pair { display: flex; justify-content: space-between; gap: 0.8em; }
    .tomb-mon { flex: 1; text-align: center; }
    .tomb-mon img { width: 56px; height: 56px; image-rendering: pixelated;
                    filter: grayscale(70%) brightness(0.7); }
    .tomb-mon .nick { color: #ddd; font-size: 0.95em; font-weight: 600; margin-top: 2px; }
    .tomb-mon .species { color: #888; font-size: 0.8em; }
    .tomb-mon .level { color: #666; font-size: 0.78em; }
    .tomb-mon .player-tag { font-size: 0.72em; color: #555; margin-bottom: 2px; }
    .tomb-divider { width: 1px; background: #2a2a35; margin: 0.5em 0; }
    .tomb-cause { text-align: center; margin-top: 0.7em; padding-top: 0.6em;
                  border-top: 1px solid #1e1e28; font-size: 0.82em; }
    .tomb-cause .cause-icon { margin-right: 0.3em; }
    .tomb-cause .cause-battle { color: #f88; }
    .tomb-cause .cause-deadzone { color: #f44; }
    .tomb-cause .cause-whiteout { color: #f80; }
    .tomb-time { text-align: center; color: #444; font-size: 0.72em; margin-top: 0.4em; }
    .tomb-num { position: absolute; top: 8px; right: 12px; color: #333; font-size: 0.7em; }
  </style>
</head>
<body>
  <h1>&#x1FAA6; <span>Memorial Wall</span></h1>
  <p class="subtitle">{page_title} &mdash; <a href="/">← Status</a></p>
  <div id="content"></div>
  <script>
  (function() {
    var FALLBACK_INTERVAL = 10000;
    var timer = null;

    function fetchAndRender() {
      fetch('/api/status').then(function(r){ return r.json(); }).then(render);
    }

    function connectSSE() {
      var es = new EventSource('/api/events');
      es.addEventListener('ping', function() { fetchAndRender(); });
      es.addEventListener('status', function(e) { render(JSON.parse(e.data)); });
      es.onerror = function() {
        if (!timer) timer = setInterval(fetchAndRender, FALLBACK_INTERVAL);
      };
      es.onopen = function() {
        if (timer) { clearInterval(timer); timer = null; }
      };
    }
    connectSSE();

    function spriteUrl(species) {
      if (!species) return '';
      return 'https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/' + species + '.png';
    }

    function render(d) {
      var kf = (d.killfeed || []).slice();
      // Sort oldest first (chronological memorial order)
      kf.sort(function(a,b) {
        return (a.killed_at || '').localeCompare(b.killed_at || '');
      });

      var el = document.getElementById('content');
      if (kf.length === 0) {
        el.innerHTML = '<p class="empty-msg">No fallen pairs yet. May your links endure.</p>';
        return;
      }

      var html = '<p class="count">' + kf.length + ' fallen pair' + (kf.length !== 1 ? 's' : '') + '</p>';
      html += '<div class="wall">';

      for (var i = 0; i < kf.length; i++) {
        var k = kf[i];
        var num = i + 1;
        var area = k.area_display || k.area_id || '?';
        var cause = k.cause || '';
        var killer = k.killer || {};
        var time = '';
        if (k.killed_at) {
          try { time = new Date(k.killed_at).toLocaleString(); } catch(e) { time = k.killed_at; }
        }

        // Cause line
        var causeHtml = '';
        if (cause === 'battle') {
          var ksp = killer.species_name || ('Species #' + (killer.species || '?'));
          var klv = killer.level ? ' Lv' + killer.level : '';
          var owner = '';
          if (killer.is_trainer && killer.trainer_name) {
            owner = (killer.trainer_class ? killer.trainer_class + ' ' : '') + killer.trainer_name + "'s ";
          } else if (killer.is_trainer) {
            owner = "Trainer's ";
          } else {
            owner = "Wild ";
          }
          causeHtml = '<span class="cause-battle"><span class="cause-icon">⚔</span>' + owner + ksp + klv + '</span>';
        } else if (cause === 'dead_zone') {
          causeHtml = '<span class="cause-deadzone"><span class="cause-icon">🚫</span>Missed catch</span>';
        } else if (cause === 'whiteout') {
          causeHtml = '<span class="cause-whiteout"><span class="cause-icon">💀</span>Whiteout</span>';
        }

        html += '<div class="tomb">';
        html += '<div class="tomb-num">#' + num + '</div>';
        html += '<div class="tomb-area">📍 ' + escHtml(area) + '</div>';
        html += '<div class="tomb-pair">';

        // Player A mon
        html += monCard(k, 'a');
        html += '<div class="tomb-divider"></div>';
        // Player B mon
        html += monCard(k, 'b');

        html += '</div>'; // tomb-pair
        if (causeHtml) html += '<div class="tomb-cause">' + causeHtml + '</div>';
        if (time) html += '<div class="tomb-time">' + escHtml(time) + '</div>';
        html += '</div>'; // tomb
      }
      html += '</div>'; // wall
      el.innerHTML = html;

      // Process RR sprites: remove solid backgrounds (funnotbun sprites have solid bg)
      el.querySelectorAll('img.mon-sprite').forEach(function(img) {
        if (img.complete && img.naturalWidth) removeBg(img);
        else img.addEventListener('load', function(){ removeBg(img); }, {once:true});
      });
    }

    var spriteCache = {};
    function removeBg(img) {
      var src = img.src;
      if (!src || !src.includes('funnotbun')) return;
      if (spriteCache[src]) { img.src = spriteCache[src]; return; }
      try {
        var c = document.createElement('canvas');
        c.width = img.naturalWidth; c.height = img.naturalHeight;
        var ctx = c.getContext('2d');
        ctx.drawImage(img, 0, 0);
        var d = ctx.getImageData(0, 0, c.width, c.height);
        var bg = [d.data[0], d.data[1], d.data[2]];
        for (var i = 0; i < d.data.length; i += 4) {
          if (Math.abs(d.data[i]-bg[0]) < 8 && Math.abs(d.data[i+1]-bg[1]) < 8 && Math.abs(d.data[i+2]-bg[2]) < 8) {
            d.data[i+3] = 0;
          }
        }
        ctx.putImageData(d, 0, 0);
        var url = c.toDataURL();
        spriteCache[src] = url;
        img.src = url;
      } catch(e) {}
    }

    function monCard(k, side) {
      var nick    = k[side + '_nickname'] || '???';
      var species = k[side + '_species_name'] || '';
      var level   = k[side + '_level'] || 0;
      var sp_html = k[side + '_sprite_html'] || '';
      var tag     = side.toUpperCase();

      var lvStr   = level ? 'Lv ' + level : '';

      return '<div class="tomb-mon">' +
        '<div class="player-tag">' + tag + '</div>' +
        sp_html +
        '<div class="nick">' + escHtml(nick) + '</div>' +
        (species ? '<div class="species">' + escHtml(species) + '</div>' : '') +
        (lvStr ? '<div class="level">' + lvStr + '</div>' : '') +
        '</div>';
    }

    function escHtml(s) {
      var d = document.createElement('div');
      d.textContent = s;
      return d.innerHTML;
    }

    fetchAndRender();
  })();
  </script>
</body>
</html>"""
