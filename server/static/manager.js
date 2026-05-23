/* manager.js — client glue for the SLink Run Manager.
 *
 * Auto-refreshes the cards grid every 10 s, keeps the stream pin indicator
 * in sync, and wires the create / start / stop / archive / delete buttons.
 */

async function refreshCards() {
  try {
    const res = await fetch('/api/runs/cards');
    if (res.ok) document.querySelector('.cards').innerHTML = await res.text();
  } catch (_) {}
  await refreshStreamPin();
}
setInterval(refreshCards, 10000);

async function refreshStreamPin() {
  try {
    const r = await fetch('/api/stream/pin');
    const j = await r.json();
    const el = document.getElementById('stream-active');
    if (!el) return;
    if (!j.active_run_name) { el.innerHTML = ''; return; }
    // Pin indicator uses the shared i-pin SVG symbol so it picks up the
    // active theme's `--c-brand` instead of rendering as a yellow emoji.
    const pinned = j.pinned
      ? ' <svg class="inline-ico" aria-hidden="true"><use href="#i-pin"/></svg>'
      : '';
    // ▶ stays as Unicode geometric arrow — it's a single-tone glyph that
    // themes via `color`. Run name is text-content so we escape via
    // textNode to avoid HTML-injection on user-provided run names.
    const arrow = document.createTextNode('▶ Active: ');
    const nameSpan = document.createTextNode(j.active_run_name);
    el.innerHTML = '';
    el.appendChild(arrow);
    el.appendChild(nameSpan);
    if (pinned) el.insertAdjacentHTML('beforeend', pinned);
  } catch (_) {}
}
refreshStreamPin();

async function pinRun(runId) {
  const r = await fetch('/api/stream/pin', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ run_id: runId })
  });
  const j = await r.json();
  if (!j.ok) alert(j.error || 'Error');
  else { await refreshStreamPin(); location.reload(); }
}

async function act(runId, action) {
  const res = await fetch(`/api/runs/${runId}/${action}`, { method: 'POST' });
  const j = await res.json();
  if (!j.ok) alert(j.error || 'Error');
  else location.reload();
}

async function archive_run(runId, name) {
  if (!confirm(`Archive run "${name}"?\n\nThis will stop the server. The run data will be preserved but the run cannot be restarted.`)) return;
  const res = await fetch(`/api/runs/${runId}/archive`, { method: 'POST' });
  const j = await res.json();
  if (!j.ok) alert(j.error || 'Error');
  else location.reload();
}

async function del_run(runId, name) {
  if (!confirm(`Delete run "${name}"?\n\nThis will stop the server and permanently delete all run data (links, memorial, etc).`)) return;
  const res = await fetch(`/api/runs/${runId}/delete`, { method: 'POST' });
  const j = await res.json();
  if (!j.ok) alert(j.error || 'Error');
  else location.reload();
}

async function newRun() {
  const name = document.getElementById('rname').value.trim();
  const species_lock = document.getElementById('species_lock').checked;
  const gender_lock = document.getElementById('gender_lock').checked;
  const type_lock = document.getElementById('type_lock').checked;
  if (!name) { alert('Enter a run name'); return; }
  const res = await fetch('/api/runs/new', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, species_lock, gender_lock, type_lock })
  });
  const j = await res.json();
  if (!j.ok) alert(j.error || 'Error');
  else location.reload();
}
